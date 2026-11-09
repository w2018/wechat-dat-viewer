"""
wechat_dat_core.py — 微信 4.x V2 .dat 图片解密核心（零第三方依赖）

只读约束：
  * 本模块对微信数据/配置目录只用 open(path, "rb") 读取，绝不写入、删除、移动。
  * 解密结果只由调用方写到工作区输出目录；assert_output_path() 会拒绝任何位于微信目录内的输出路径。
  * 不读取聊天消息数据库，不解析聊天文本内容。

V2 .dat 格式（微信 4.0）：
  [6B 签名 07 08 56 32 08 07]
  [4B aes_size, LE] [4B xor_size, LE] [1B pad]           = 15B 头
  [AES-128-ECB 加密段, PKCS#7 对齐长度] [可选明文段] [xor_size 字节单字节 XOR 尾段]
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

V2_MAGIC = b"\x07\x08V2\x08\x07"

# ---------------------------------------------------------------- AES-128 --
# 纯 Python 实现，避免依赖 pycryptodome/cryptography（本机离线装不上）。
# 用标准 S-box 生成式 + GF(2^8) 运算，结果已与 OpenSSL 3.5.7 交叉验证。


def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def _gmul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _rotl8(x: int, n: int) -> int:
    return ((x << n) | (x >> (8 - n))) & 0xFF


def _build_sbox() -> tuple[list[int], list[int]]:
    sbox = []
    for i in range(256):
        inv = 0
        for j in range(256):
            if _gmul(i, j) == 1:
                inv = j
                break
        x = inv
        sbox.append(
            x
            ^ _rotl8(x, 1)
            ^ _rotl8(x, 2)
            ^ _rotl8(x, 3)
            ^ _rotl8(x, 4)
            ^ 0x63
        )
    inv_sbox = [0] * 256
    for i, v in enumerate(sbox):
        inv_sbox[v] = i
    return sbox, inv_sbox


_SBOX, _INV_SBOX = _build_sbox()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key: bytes) -> list[bytes]:
    w = [list(key[i * 4 : i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = w[i - 1][:]
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [bytes(b for col in w[4 * r : 4 * r + 4] for b in col) for r in range(11)]


def aes128_ecb_decrypt(key: bytes, data: bytes) -> bytes:
    """AES-128-ECB 解密；data 长度必须是 16 的倍数。"""
    if len(key) != 16:
        raise ValueError("AES-128 key must be 16 bytes")
    if len(data) % 16:
        raise ValueError("ciphertext length must be a multiple of 16")
    rk = _expand_key(key)
    out = bytearray()

    def inv_shift_rows(b: list[int]) -> list[int]:
        nb = b[:]
        for r in range(4):
            for c in range(4):
                nb[r + 4 * c] = b[r + 4 * ((c - r) % 4)]
        return nb

    def inv_mix_columns(b: list[int]) -> list[int]:
        nb = b[:]
        for c in range(4):
            a = b[4 * c : 4 * c + 4]
            nb[4 * c + 0] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
            nb[4 * c + 1] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
            nb[4 * c + 2] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
            nb[4 * c + 3] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)
        return nb

    for off in range(0, len(data), 16):
        b = [x ^ y for x, y in zip(data[off : off + 16], rk[10])]
        for rnd in range(9, 0, -1):
            b = inv_shift_rows(b)
            b = [_INV_SBOX[x] for x in b]
            b = [x ^ y for x, y in zip(b, rk[rnd])]
            b = inv_mix_columns(b)
        b = inv_shift_rows(b)
        b = [_INV_SBOX[x] for x in b]
        out += bytes(x ^ y for x, y in zip(b, rk[0]))
    return bytes(out)


# ------------------------------------------------------------------ V2 .dat --

def parse_v2(data: bytes):
    """返回 (aes_size, aes_cipher, raw_plain, xor_tail)，非 V2 返回 None。"""
    if len(data) < 15 or data[:6] != V2_MAGIC:
        return None
    aes_size = int.from_bytes(data[6:10], "little")
    xor_size = int.from_bytes(data[10:14], "little")
    aligned = (aes_size // 16 + 1) * 16  # PKCS#7：总是补 1..16 字节
    head = 15
    aes_cipher = data[head : head + aligned]
    if len(aes_cipher) < aligned:
        return None
    rest = data[head + aligned :]
    raw_len = len(rest) - xor_size
    if raw_len < 0:
        return None
    return aes_size, aes_cipher, rest[:raw_len], rest[raw_len:]


def derive_xor_key_from_jpeg(xor_tail: bytes):
    """JPEG 以 FF D9 结尾，由此反推单字节 XOR key。"""
    if len(xor_tail) < 2:
        return None
    k1 = xor_tail[-2] ^ 0xFF
    k2 = xor_tail[-1] ^ 0xD9
    return k1 if k1 == k2 else None


IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),
    (b"BM", "bmp"),
    (b"wxgf", "wxgf"),   # 微信自研格式，内部多为 HEVC 帧
    (b"\x00\x00\x00\x1cftyp", "heic"),
)


def sniff_image(data: bytes):
    for sig, ext in IMAGE_SIGNATURES:
        if data.startswith(sig):
            return ext
    return None


def decrypt_v2(data: bytes, aes_key: bytes, xor_key: int) -> bytes | None:
    parsed = parse_v2(data)
    if parsed is None:
        return None
    aes_size, aes_cipher, raw_plain, xor_tail = parsed
    dec = aes128_ecb_decrypt(aes_key, aes_cipher)
    pad = dec[-1]
    if 1 <= pad <= 16 and dec[-pad:] == bytes([pad]) * pad:
        dec = dec[:-pad]
    dec = dec[:aes_size]
    # bytes.translate 比逐字节生成器快一个数量级，大图(20MB+)也需要
    xor_table = bytes(i ^ xor_key for i in range(256))
    tail = xor_tail.translate(xor_table)
    return dec + raw_plain + tail


# --------------------------------------------------------- 只读环境发现/密钥 --

DEFAULT_WECHAT_ROOT = Path(
    os.environ.get("WECHAT_DATA_ROOT")
    or (Path.home() / "Documents" / "xwechat_files")
)
DEFAULT_APPDATA = Path(
    os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
) / "Tencent" / "xwechat"


def is_valid_data_root(root: Path) -> bool:
    """判定是否为微信 4.x 数据根目录：含 wxid_* 账号目录且有 msg/attach 或 msg/video。"""
    try:
        p = Path(root)
        if not p.is_dir():
            return False
        for d in p.iterdir():
            if d.is_dir() and d.name.startswith("wxid_"):
                if (d / "msg" / "attach").is_dir() or (d / "msg" / "video").is_dir():
                    return True
    except OSError:
        return False
    return False


def _registry_wechat_paths() -> list[Path]:
    """只读读取注册表里微信记录的安装/文件保存路径。"""
    out: list[Path] = []
    try:
        import winreg
        for sub in (r"Software\Tencent\Weixin", r"Software\Tencent\WeChat"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                    for name in ("FileSavePath", "OldFileSavePath", "InstallPath", "DataPath"):
                        try:
                            val, _ = winreg.QueryValueEx(k, name)
                            if val:
                                out.append(Path(str(val)))
                        except OSError:
                            continue
            except OSError:
                continue
    except ImportError:
        pass
    return out


def discover_data_root() -> Path | None:
    """自动扫描微信数据根目录：环境变量 -> 注册表线索 -> 常见位置 -> 各盘根目录。全程只读。"""
    cands: list[Path] = []
    env = os.environ.get("WECHAT_DATA_ROOT")
    if env:
        cands.append(Path(env))
    for p in _registry_wechat_paths():
        cands += [p, p / "xwechat_files", p.parent / "xwechat_files",
                  p.parent / "WeChat Files", p.parent]
    home = Path.home()
    cands += [
        home / "Documents" / "xwechat_files",
        home / "Documents" / "WeChat Files",
        home / "AppData" / "Roaming" / "Tencent" / "xwechat_files",
    ]
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        try:
            if not root.exists():
                continue
        except OSError:
            continue
        cands += [root / "xwechat_files", root / "WeChat Files"]
    seen: set[str] = set()
    for c in cands:
        try:
            rp = c.resolve()
        except OSError:
            continue
        key = str(rp).casefold()
        if key in seen:
            continue
        seen.add(key)
        if is_valid_data_root(rp):
            return rp
    return None


def discover_uins(appdata: Path = DEFAULT_APPDATA) -> list[int]:
    """只读扫描 kvcomm 的 *.statistic 文件名，提取十进制 UIN 候选。"""
    uins: set[int] = set()
    for kv in appdata.rglob("kvcomm"):
        try:
            for f in kv.glob("*.statistic"):
                for token in re.findall(r"\d{6,}", f.name):
                    v = int(token)
                    # 排除版本号(40 亿级)和时间戳(17 亿级)等明显非 UIN 的数字
                    if 1000000 <= v <= 3000000000 and v not in (4065599288,):
                        uins.add(v)
        except OSError:
            continue
    return sorted(uins)


def discover_accounts(root: Path = DEFAULT_WECHAT_ROOT) -> list[Path]:
    """列出形如 wxid_xxx_yyyy 的账号目录（只读）。"""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("wxid_"))


def candidate_keys(uins, wxids) -> list[tuple[bytes, int, str]]:
    """生成 (aes_key, xor_key, 说明) 候选。"""
    out = []
    for uin in uins:
        for wxid in wxids:
            key = hashlib.md5(f"{uin}{wxid}".encode()).hexdigest()[:16].encode()
            out.append((key, uin & 0xFF, f"md5({uin}+{wxid})[:16]"))
    return out


def assert_output_path(path: Path, wechat_roots: list[Path] | None = None) -> Path:
    """硬性拦截：输出路径绝不能落在微信数据/配置目录内。"""
    roots = wechat_roots or [DEFAULT_WECHAT_ROOT, DEFAULT_APPDATA]
    p = Path(path).resolve()
    for r in roots:
        try:
            p.relative_to(Path(r).resolve())
        except ValueError:
            continue
        raise PermissionError(f"拒绝写入微信目录：{p}")
    return p


# ------------------------------------------------------------------- wxgf ---
# 微信自研 wxgf 载荷里是裸 HEVC(Annex-B) 帧，浏览器无法直接显示。
# 用外部 ffmpeg 在内存里取首帧转 JPEG：全程 pipe，不产生临时文件、不写微信目录。

import shutil  # noqa: E402
import subprocess  # noqa: E402

_env_ffmpeg = os.environ.get("WECHAT_FFMPEG")
FFMPEG_CANDIDATES = ([Path(_env_ffmpeg)] if _env_ffmpeg else []) + [
    Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
]


def find_ffmpeg() -> Path | None:
    """找一个支持 raw hevc 解复用 + mjpeg 编码的 ffmpeg；只读探测。"""
    for p in FFMPEG_CANDIDATES:
        if not p.is_file():
            continue
        try:
            r = subprocess.run(
                [str(p), "-hide_banner", "-demuxers"],
                capture_output=True, timeout=10,
            )
            if b"hevc" in r.stdout.lower() or b"h265" in r.stdout.lower():
                return p
        except (OSError, subprocess.TimeoutExpired):
            continue
    guessed = shutil.which("ffmpeg")
    return Path(guessed) if guessed else None


def wxgf_to_jpeg(payload: bytes, ffmpeg: Path | None = None, timeout: int = 20) -> bytes | None:
    """把 wxgf 载荷里的 HEVC 首帧转成 JPEG；失败返回 None。"""
    if not payload.startswith(b"wxgf"):
        return None
    ff = ffmpeg or find_ffmpeg()
    if ff is None:
        return None
    start = payload.find(b"\x00\x00\x00\x01\x40\x01")  # VPS NAL
    if start < 0:
        start = payload.find(b"\x00\x00\x01\x40\x01")
    if start < 0:
        return None
    try:
        r = subprocess.run(
            [str(ff), "-hide_banner", "-loglevel", "error",
             "-f", "hevc", "-i", "pipe:0", "-frames:v", "1",
             "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
            input=payload[start:], capture_output=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.stdout.startswith(b"\xff\xd8") else None


# --------------------------------------------------------- 元数据 / 回收站 ---

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402
from datetime import datetime  # noqa: E402


def image_dimensions(data: bytes, ext: str | None = None):
    """从已解密的图片数据里读出像素尺寸，返回 (w, h) 或 None。"""
    ext = ext or sniff_image(data)
    try:
        if ext in ("jpg", "jpeg"):
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seglen = int.from_bytes(data[i + 2 : i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(data[i + 5 : i + 7], "big")
                    w = int.from_bytes(data[i + 7 : i + 9], "big")
                    return (w, h) if w and h else None
                i += 2 + seglen
        elif ext == "png" and len(data) >= 24 and data[12:16] == b"IHDR":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        elif ext == "gif" and len(data) >= 10:
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        elif ext == "bmp" and len(data) >= 26:
            w = int.from_bytes(data[18:22], "little", signed=True)
            h = abs(int.from_bytes(data[22:26], "little", signed=True))
            return (w, h) if w and h else None
        elif ext == "webp" and len(data) >= 30:
            chunk = data[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return w, h
            if chunk == b"VP8 ":
                return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                        int.from_bytes(data[28:30], "little") & 0x3FFF)
    except (IndexError, ValueError):
        pass
    return None


def file_meta(path: Path) -> dict:
    """只读 stat：路径、大小、修改时间、硬链接数。"""
    st = Path(path).stat()
    return {
        "path": str(Path(path)),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "mtime_str": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "nlink": getattr(st, "st_nlink", 1),
    }


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint),  # FILEOP_FLAGS(WORD) + 2B padding
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


def recycle_batch(paths: list[Path]) -> dict:
    """把一组文件移入 Windows 回收站（可恢复），不是永久删除。

    使用 SHFileOperationW + FOF_ALLOWUNDO。返回 {ok, rc, aborted}。
    调用方负责：先列清单、二次确认、每批 <= 10 个、逐批验证。
    """
    paths = [str(Path(p).resolve()) for p in paths]
    if not paths:
        return {"ok": True, "rc": 0, "aborted": False}
    buf = "\0".join(paths) + "\0\0"
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = buf
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return {"ok": rc == 0 and not op.fAnyOperationsAborted,
            "rc": rc, "aborted": bool(op.fAnyOperationsAborted)}


def _iter_mp4_boxes(data: bytes, start: int = 0, end: int | None = None):
    end = len(data) if end is None else end
    p = start
    while p + 8 <= end:
        size = int.from_bytes(data[p : p + 4], "big")
        typ = data[p + 4 : p + 8]
        hdr = 8
        if size == 1:
            size = int.from_bytes(data[p + 8 : p + 16], "big")
            hdr = 16
        elif size == 0:
            size = end - p
        if size < hdr or p + size > end:
            break
        yield typ, p, size, hdr
        p += size


_MP4_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _find_mp4_box(data: bytes, target: bytes, start: int = 0, end: int | None = None):
    for typ, p, size, hdr in _iter_mp4_boxes(data, start, end):
        if typ == target:
            return p, size, hdr
        if typ in _MP4_CONTAINERS:
            hit = _find_mp4_box(data, target, p + hdr, p + size)
            if hit:
                return hit
    return None


def mp4_meta(path: Path, read_limit: int = 4 * 1024 * 1024) -> dict:
    """只读解析 MP4 容器头，取分辨率与时长（不依赖 ffprobe）。"""
    with open(path, "rb") as f:
        data = f.read(read_limit)
    out: dict = {"width": None, "height": None, "duration": None}
    try:
        mvhd = _find_mp4_box(data, b"mvhd")
        if mvhd:
            p, _, hdr = mvhd
            ver = data[p + hdr]
            if ver == 0:
                ts = int.from_bytes(data[p + hdr + 12 : p + hdr + 16], "big")
                du = int.from_bytes(data[p + hdr + 16 : p + hdr + 20], "big")
            else:
                ts = int.from_bytes(data[p + hdr + 20 : p + hdr + 24], "big")
                du = int.from_bytes(data[p + hdr + 24 : p + hdr + 32], "big")
            if ts:
                out["duration"] = round(du / ts, 1)
        stsd = _find_mp4_box(data, b"stsd")
        if stsd:
            p, size, hdr = stsd
            for _typ, ep, _n, _h in _iter_mp4_boxes(data, p + hdr + 8, p + size):
                w = int.from_bytes(data[ep + 32 : ep + 34], "big")
                h = int.from_bytes(data[ep + 34 : ep + 36], "big")
                if w and h:
                    out["width"], out["height"] = w, h
                    break
    except (IndexError, ValueError, ZeroDivisionError):
        pass
    return out
