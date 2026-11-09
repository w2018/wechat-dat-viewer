#!/usr/bin/env python
"""
wechat_dat_viewer.py — 微信 4.x 图片/视频查看器（零第三方依赖，双分区）

默认只读：
  * 微信目录只用 open(..., 'rb') 读取；看图/播放走内存 HTTP 响应，不落盘。
  * 不打开消息数据库、不解析聊天文本；HTTP 只绑定 127.0.0.1。

需要删除能力时必须显式加 --allow-delete，且：
  1) 先 POST /api/delete/preview 得到完整文件清单 + 一次性令牌；
  2) 前端展示警告与清单，要求手工输入确认词；
  3) POST /api/delete/commit 校验令牌 + 确认词后才分批(<=10)移入系统回收站；
  4) 每批验证、失败即停，全程写 JSONL 日志到工作区。
  删除的是媒体文件，绝不触碰数据库/配置；回收站可恢复。

用法：
  python wechat_dat_viewer.py probe
  python wechat_dat_viewer.py serve --port 56789 [--allow-delete] [--open]
  python wechat_dat_viewer.py export --session <hash> --month 2026-09 --out <目录> [--limit 50]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import secrets
import sys
import time
import webbrowser
import zipfile
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

from wechat_dat_core import (  # noqa: E402
    aes128_ecb_decrypt,
    DEFAULT_APPDATA,
    DEFAULT_WECHAT_ROOT,
    assert_output_path,
    candidate_keys,
    decrypt_v2,
    derive_xor_key_from_jpeg,
    discover_accounts,
    discover_data_root,
    discover_uins,
    file_meta,
    is_valid_data_root,
    find_ffmpeg,
    image_dimensions,
    mp4_meta,
    parse_v2,
    recycle_batch,
    sniff_image,
    wxgf_to_jpeg,
)

DEFAULT_CSV = TOOL_DIR / "sessions.csv"
DEFAULT_EXPORT = TOOL_DIR / "exports" / "images"
EXPORT_DIR = TOOL_DIR / "exports"
DELETE_LOG = TOOL_DIR / "delete_log.jsonl"
CONFIG_FILE = TOOL_DIR / "wechat_data_root.dat"   # 运行时生成，已被 .gitignore 排除


def load_saved_root() -> Path | None:
    """读取当前文件夹下 .dat 配置里上次确认的数据根目录。"""
    try:
        s = CONFIG_FILE.read_text(encoding="utf-8").strip()
        return Path(s) if s else None
    except OSError:
        return None


def save_root(root: Path) -> None:
    """把数据根目录持久化到当前文件夹的 .dat 文件（绝不写入微信目录）。"""
    assert_output_path(CONFIG_FILE)
    try:
        CONFIG_FILE.write_text(str(Path(root).resolve()), encoding="utf-8")
    except OSError as e:
        print(f"警告：无法保存配置 {CONFIG_FILE}: {e}", file=sys.stderr)


def resolve_data_root(cli_value: str | None) -> Path:
    """优先级：--data-root > .dat 缓存 > 自动扫描 > 明确报错。"""
    if cli_value:
        p = Path(cli_value).resolve()
        if not is_valid_data_root(p):
            raise FileNotFoundError(f"指定的目录不是有效的微信 4.x 数据根目录：{p}")
        save_root(p)
        return p
    saved = load_saved_root()
    if saved and is_valid_data_root(saved):
        return saved.resolve()
    found = discover_data_root()
    if found:
        save_root(found)
        return found
    raise FileNotFoundError(
        "未找到微信 4.x 数据目录。可设置环境变量 WECHAT_DATA_ROOT，"
        "或用 --data-root <路径> 指定（其下应有 wxid_* / msg / attach）。"
    )


# 格式无法预览/播放时的简洁占位提示
HINT_NEED_FFMPEG = "不支持预览，需要 ffmpeg"
HINT_NEED_TRANSCODE = "不支持预览，需要转码"
HINT_NEED_COVER = "不支持预览，需要封面"
HINT_NEED_DECODER = "不支持播放，需要解码器"


def placeholder_svg(text: str) -> bytes:
    """生成一张文字占位图，避免浏览器显示破图。"""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200">'
        '<rect width="320" height="200" fill="#f1f3f6"/>'
        '<rect x="0.5" y="0.5" width="319" height="199" fill="none" stroke="#dfe3e8"/>'
        '<text x="160" y="100" text-anchor="middle" dominant-baseline="middle" '
        'font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="15" fill="#6b7280">'
        + escape(text) + "</text></svg>"
    )
    return svg.encode("utf-8")


SID_RE = re.compile(r"^[0-9a-f]{32}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
BASE_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ZIP_RE = re.compile(r"^wechat_(image|video)_\d{8}_\d{6}_[0-9a-f]{6}\.zip$")

MIME = {
    "jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "heic": "image/heic",
}
EXT_OF_MIME = {v: k for k, v in MIME.items()}
MEDIA_EXTS = {".dat", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".bmp"}
CONFIRM_WORD = "MOVE_TO_RECYCLE_BIN"
BATCH_SIZE = 10
TOKEN_TTL = 600


class Viewer:
    def __init__(self, data_root: Path, account: str | None, sessions_csv: Path,
                 ffmpeg: Path | None, allow_delete: bool = False):
        self.data_root = Path(data_root).resolve()
        self.account = account or self._pick_account()
        self.attach = self.data_root / self.account / "msg" / "attach"
        self.video_dir = self.data_root / self.account / "msg" / "video"
        self.allow_delete = allow_delete
        if not self.attach.is_dir():
            raise FileNotFoundError(f"找不到图片附件目录：{self.attach}")
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self.sessions_meta = self._load_sessions_csv(sessions_csv)
        self.aes_key: bytes | None = None
        self.xor_key: int | None = None
        self.key_desc = ""
        self._tokens: dict[str, dict] = {}
        self._meta_cache: dict[tuple, dict] = {}
        self._ff_cache: dict[tuple, bool] = {}
        self._resolve_keys()

    # ------------------------------------------------------------ 初始化 ---
    def _pick_account(self) -> str:
        accounts = discover_accounts(self.data_root)
        if not accounts:
            raise FileNotFoundError(f"{self.data_root} 下没有 wxid_ 账号目录")
        return max(accounts, key=lambda p: p.stat().st_mtime).name

    @staticmethod
    def _load_sessions_csv(path: Path) -> dict[str, dict]:
        meta: dict[str, dict] = {}
        if not path.is_file():
            return meta
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    sid = row.get("session_hash", "").strip()
                    if SID_RE.match(sid):
                        meta[sid] = {
                            "size_mb": float(row.get("logical_size_MB") or row.get("size_MB") or 0),
                            "file_count": int(row.get("file_count") or 0),
                        }
        except (OSError, ValueError):
            pass
        return meta

    def _find_sample(self) -> Path | None:
        for sess in self.attach.iterdir():
            if not sess.is_dir():
                continue
            for month in sess.iterdir():
                img = month / "Img"
                if img.is_dir():
                    hit = next(img.glob("*_t.dat"), None)
                    if hit:
                        return hit
        return None

    def _resolve_keys(self) -> None:
        sample = self._find_sample()
        if sample is None:
            raise RuntimeError("找不到用于验证密钥的 .dat 样本")
        raw = sample.read_bytes()
        parsed = parse_v2(raw)
        derived = derive_xor_key_from_jpeg(parsed[3]) if parsed else None
        uins = discover_uins(DEFAULT_APPDATA)
        short = self.account.rsplit("_", 1)[0] if self.account.count("_") >= 2 else self.account
        for key, seed_xor, desc in candidate_keys(uins, [short, self.account]):
            for xk in {k for k in (derived, seed_xor) if k is not None}:
                try:
                    out = decrypt_v2(raw, key, xk)
                except Exception:
                    continue
                if out and sniff_image(out) in ("jpg", "png", "gif", "webp", "bmp", "wxgf"):
                    self.aes_key, self.xor_key, self.key_desc = key, xk, desc
                    return
        raise RuntimeError("密钥推导失败：请确认 UIN / wxid，或用 probe 子命令诊断")

    # --------------------------------------------------------- 路径安全 ---
    def _safe_media(self, p: Path) -> Path:
        rp = Path(p).resolve()
        rp.relative_to(self.data_root)              # 必须在微信数据根下
        if rp.suffix.lower() not in MEDIA_EXTS:    # 只允许媒体文件
            raise PermissionError(f"非媒体文件，拒绝操作：{rp}")
        if "db_storage" in rp.parts or rp.suffix.lower() in (".db", ".db-wal", ".db-shm"):
            raise PermissionError(f"拒绝操作数据库文件：{rp}")
        return rp

    # ------------------------------------------------------------ 图片区 ---
    @staticmethod
    def _session_dates(d: Path, months: list[str]):
        """只读取每个月份目录里一个文件的 mtime，得到该会话大致起止年月日。"""
        times: list[float] = []
        for m in months:
            img = d / m / "Img"
            if not img.is_dir():
                continue
            try:
                with os.scandir(img) as it:
                    for e in it:
                        if e.is_file():
                            times.append(e.stat().st_mtime)
                            break
            except OSError:
                pass
        if not times:
            return None, None
        return (datetime.fromtimestamp(min(times)).strftime("%Y-%m-%d"),
                datetime.fromtimestamp(max(times)).strftime("%Y-%m-%d"))

    def sessions(self) -> list[dict]:
        out = []
        for d in self.attach.iterdir():
            if not d.is_dir() or not SID_RE.match(d.name):
                continue
            months = sorted(m.name for m in d.iterdir() if m.is_dir() and MONTH_RE.match(m.name))
            meta = self.sessions_meta.get(d.name, {})
            first_date, last_date = self._session_dates(d, months)
            out.append({
                "sid": d.name,
                "size_mb": round(meta.get("size_mb", 0), 1),
                "file_count": meta.get("file_count", 0),
                "months": months,
                "first_date": first_date,
                "last_date": last_date,
            })
        # 下拉框按最新日期倒序（新 -> 旧），同日再按占用大小倒序
        out.sort(key=lambda x: (x["last_date"] or "", x["size_mb"]), reverse=True)
        return out

    def months(self, sid: str) -> list[str]:
        if not SID_RE.match(sid):
            return []
        return sorted(m.name for m in (self.attach / sid).iterdir()
                      if m.is_dir() and MONTH_RE.match(m.name))

    def image_group_paths(self, sid: str, month: str, base: str) -> list[Path]:
        if not (SID_RE.match(sid) and MONTH_RE.match(month) and BASE_RE.match(base)):
            return []
        img = self.attach / sid / month / "Img"
        names = [f"{base}.dat", f"{base}_h.dat", f"{base}_t.dat"]
        return [self._safe_media(img / n) for n in names if (img / n).is_file()]

    @staticmethod
    def _group_files(img_dir: Path) -> list[dict]:
        groups: dict[str, dict] = {}
        for f in img_dir.iterdir():
            if not f.is_file() or f.suffix.lower() != ".dat":
                continue
            stem = f.stem
            if stem.endswith("_h"):
                base, variant = stem[:-2], "hd"
            elif stem.endswith("_t"):
                base, variant = stem[:-2], "thumb"
            else:
                base, variant = stem, "main"
            if not BASE_RE.match(base):
                continue
            g = groups.setdefault(base, {"base": base, "variants": {}, "size": 0})
            g["variants"][variant] = f.name
            g["size"] += f.stat().st_size
        return [{"base": g["base"], "size": g["size"],
                 "has_hd": "hd" in g["variants"], "has_thumb": "thumb" in g["variants"]}
                for g in sorted(groups.values(), key=lambda x: x["base"])]

    def images(self, sid: str, month: str, offset: int, limit: int):
        if not SID_RE.match(sid) or not MONTH_RE.match(month):
            return 0, []
        img = self.attach / sid / month / "Img"
        if not img.is_dir():
            return 0, []
        items = self._group_files(img)
        return len(items), (items[offset:offset + limit] if limit > 0 else items)

    def needs_ffmpeg(self, sid: str, month: str, base: str) -> bool:
        """只读文件前 1KB，判断明文头是否为 wxgf（需要 ffmpeg 才能预览）。"""
        key = (sid, month, base)
        if key in self._ff_cache:
            return self._ff_cache[key]
        img = self.attach / sid / month / "Img"
        hit = False
        for name in (f"{base}_h.dat", f"{base}.dat"):
            p = img / name
            if not p.is_file():
                continue
            try:
                with open(p, "rb") as f:
                    raw = f.read(15 + 1040)
                if len(raw) < 31:
                    continue
                aes_size = int.from_bytes(raw[6:10], "little")
                aligned = (aes_size // 16 + 1) * 16
                dec = aes128_ecb_decrypt(self.aes_key, raw[15:15 + aligned])
                if dec.startswith(b"wxgf"):
                    hit = True
                    break
            except Exception:
                continue
        self._ff_cache[key] = hit
        return hit

    def image_bytes(self, sid: str, month: str, base: str, kind: str):
        if not (SID_RE.match(sid) and MONTH_RE.match(month) and BASE_RE.match(base)):
            return None, None
        img = (self.attach / sid / month / "Img").resolve()
        try:
            img.relative_to(self.attach.resolve())
        except ValueError:
            return None, None
        # 缺 ffmpeg 且原图为 wxgf：缩略图与大图都显示简洁占位提示
        if self.ffmpeg is None and self.needs_ffmpeg(sid, month, base):
            return None, None
        names = ([f"{base}_h.dat", f"{base}.dat", f"{base}_t.dat"] if kind == "full"
                 else [f"{base}_t.dat", f"{base}.dat", f"{base}_h.dat"])
        for name in names:
            p = img / name
            if not p.is_file():
                continue
            try:
                payload = decrypt_v2(p.read_bytes(), self.aes_key, self.xor_key)
            except Exception:
                continue
            if not payload:
                continue
            ext = sniff_image(payload)
            if ext == "wxgf":
                jpg = wxgf_to_jpeg(payload, self.ffmpeg)
                if jpg:
                    return jpg, "image/jpeg"
                continue
            mime = MIME.get(ext or "")
            if mime:
                return payload, mime
        return None, None

    # ------------------------------------------------------------ 视频区 ---
    def video_months(self) -> list[str]:
        if not self.video_dir.is_dir():
            return []
        return sorted(m.name for m in self.video_dir.iterdir()
                      if m.is_dir() and MONTH_RE.match(m.name))

    def video_group_paths(self, month: str, base: str) -> list[Path]:
        if not (MONTH_RE.match(month) and BASE_RE.match(base)):
            return []
        d = self.video_dir / month
        names = [f"{base}.mp4", f"{base}_thumb.jpg", f"{base}.jpg"]
        return [self._safe_media(d / n) for n in names if (d / n).is_file()]

    def videos(self, month: str, offset: int, limit: int):
        if not MONTH_RE.match(month):
            return 0, []
        d = self.video_dir / month
        if not d.is_dir():
            return 0, []
        items = []
        for f in sorted(d.glob("*.mp4")):
            base = f.stem
            if not BASE_RE.match(base):
                continue
            size = f.stat().st_size
            for extra in (f"{base}_thumb.jpg", f"{base}.jpg"):
                ep = d / extra
                if ep.is_file():
                    size += ep.stat().st_size
            # 视频分区只展示日期与大小，不做分辨率/时长解析
            items.append({"base": base, "size": size,
                          "date": file_meta(f)["mtime_str"],
                          "has_thumb": (d / f"{base}_thumb.jpg").is_file() or (d / f"{base}.jpg").is_file()})
        return len(items), (items[offset:offset + limit] if limit > 0 else items)

    def video_thumb(self, month: str, base: str):
        if not (MONTH_RE.match(month) and BASE_RE.match(base)):
            return None, None
        d = self.video_dir / month
        for name in (f"{base}_thumb.jpg", f"{base}.jpg"):
            p = d / name
            if p.is_file():
                return self._safe_media(p).read_bytes(), "image/jpeg"
        return None, None

    def video_stream(self, month: str, base: str, range_header: str | None):
        if not (MONTH_RE.match(month) and BASE_RE.match(base)):
            return None
        p = self._safe_media(self.video_dir / month / f"{base}.mp4")
        size = p.stat().st_size
        start, end = 0, max(0, size - 1)
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), end)
        start = min(start, max(0, size - 1))
        end = max(start, min(end, size - 1))
        with open(p, "rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)
        return {"data": data, "start": start, "end": end, "size": size}

    # -------------------------------------------------------------- 元数据 ---
    def info(self, zone: str, sid: str, month: str, base: str) -> dict:
        key = (zone, sid, month, base)
        if key in self._meta_cache:
            return self._meta_cache[key]
        if zone == "image":
            files = self.image_group_paths(sid, month, base)
            data, mime = self.image_bytes(sid, month, base, "full")
            ext = (sniff_image(data) if data else None) or ""
            wh = image_dimensions(data) if data else None
            fmt = ("JPEG" if mime == "image/jpeg" else (mime or "").split("/")[-1].upper())
            if not data:
                fmt = "需要 ffmpeg" if not self.ffmpeg else "无法解码"
            if data and data.startswith(b"wxgf"):
                fmt = "wxgf (HEVC→JPEG)"
            out = {"zone": "image", "base": base, "month": month, "sid": sid,
                   "files": [file_meta(p) for p in files],
                   "total_size": sum(f["size"] for f in [file_meta(p) for p in files]),
                   "width": wh[0] if wh else None, "height": wh[1] if wh else None,
                   "duration": None, "format": fmt}
        else:
            # 悬浮信息保持完整（分区/格式/尺寸/时长/合计/逐文件路径与日期大小）
            files = self.video_group_paths(month, base)
            mp4 = self.video_dir / month / f"{base}.mp4"
            vm = mp4_meta(mp4) if mp4.is_file() else {}
            metas = [file_meta(p) for p in files]
            out = {"zone": "video", "base": base, "month": month, "sid": "",
                   "files": metas, "total_size": sum(f["size"] for f in metas),
                   "width": vm.get("width"), "height": vm.get("height"),
                   "duration": vm.get("duration"), "format": "MP4 (明文)"}
        self._meta_cache[key] = out
        return out

    # ---------------------------------------------------------- 批量目标 ---
    def resolve_targets(self, payload: dict) -> list[dict]:
        zone = payload.get("zone")
        month = payload.get("month", "")
        sid = payload.get("sid", "")
        bases = payload.get("bases", [])
        if zone not in ("image", "video") or not MONTH_RE.match(month):
            raise ValueError("分区或月份无效")
        if len(bases) > 500:
            raise ValueError("单次最多 500 项，请分批操作")
        out = []
        for base in bases:
            if not BASE_RE.match(str(base)):
                continue
            paths = (self.image_group_paths(sid, month, base) if zone == "image"
                     else self.video_group_paths(month, base))
            if not paths:
                continue
            metas = [file_meta(p) for p in paths]
            out.append({"base": base, "files": metas,
                        "size": sum(m["size"] for m in metas),
                        "nlink_max": max(m["nlink"] for m in metas)})
        return out

    # ------------------------------------------------------------ 批量导出 ---
    def make_export(self, payload: dict) -> dict:
        targets = self.resolve_targets(payload)
        if not targets:
            raise ValueError("没有可导出的文件")
        if sum(t["size"] for t in targets) > 2 * 1024 ** 3:
            raise ValueError("单次导出超过 2GB，请分批")
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        assert_output_path(EXPORT_DIR, wechat_roots=[self.data_root, DEFAULT_APPDATA])
        name = f"wechat_{payload['zone']}_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.zip"
        zp = EXPORT_DIR / name
        zone, month, sid = payload["zone"], payload["month"], payload.get("sid", "")
        count = 0
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
            for t in targets:
                base = t["base"]
                if zone == "image":
                    data, mime = self.image_bytes(sid, month, base, "full")
                    if data:
                        ext = EXT_OF_MIME.get(mime, "jpg")
                        z.writestr(f"{month}_{base}.{ext}", data)
                        count += 1
                else:
                    mp4 = self.video_dir / month / f"{base}.mp4"
                    if mp4.is_file():
                        z.write(self._safe_media(mp4), arcname=f"{month}_{base}.mp4")
                        count += 1
                    thumb, _ = self.video_thumb(month, base)
                    if thumb:
                        z.writestr(f"{month}_{base}_thumb.jpg", thumb)
        return {"name": name, "path": str(zp), "count": count,
                "bytes": zp.stat().st_size, "dir": str(EXPORT_DIR)}

    # ------------------------------------------------------------ 删除链路 ---
    def preview_delete(self, payload: dict) -> dict:
        if not self.allow_delete:
            raise PermissionError("删除功能未启用：启动服务时需加 --allow-delete")
        targets = self.resolve_targets(payload)
        if not targets:
            raise ValueError("没有可删除的文件")
        files = [f for t in targets for f in t["files"]]
        token = secrets.token_urlsafe(24)
        self._tokens[token] = {"ts": time.time(), "targets": targets,
                              "zone": payload["zone"], "month": payload["month"],
                              "sid": payload.get("sid", "")}
        return {
            "token": token, "confirm_word": CONFIRM_WORD,
            "group_count": len(targets), "file_count": len(files),
            "total_size": sum(f["size"] for f in files),
            "hardlinked_files": sum(1 for f in files if f["nlink"] > 1),
            "files": files,
            "warning": "此操作非常危险，可能导致不可逆的数据丢失！文件将被移入系统回收站；"
                       "微信聊天记录中的对应图片/视频会失效，且微信可能重新下载。",
        }

    def _append_log(self, record: dict) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        with DELETE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def commit_delete(self, token: str, confirm: str) -> dict:
        if not self.allow_delete:
            raise PermissionError("删除功能未启用")
        rec = self._tokens.pop(token, None)
        if not rec or time.time() - rec["ts"] > TOKEN_TTL:
            raise ValueError("确认令牌无效或已过期，请重新预览")
        if confirm != CONFIRM_WORD:
            raise ValueError("二次确认未通过：确认词不正确")
        all_paths = [f["path"] for t in rec["targets"] for f in t["files"]]
        deleted: list[str] = []
        failed: list[str] = []
        batches = 0
        for i in range(0, len(all_paths), BATCH_SIZE):
            batch = all_paths[i:i + BATCH_SIZE]
            # 提交前再校验一次，防止清单生成后路径被替换
            batch = [str(self._safe_media(Path(x))) for x in batch]
            r = recycle_batch([Path(x) for x in batch])
            still = [x for x in batch if Path(x).exists()]
            if not r["ok"] or still:
                failed.extend(still or batch)
                break
            deleted.extend(batch)
            batches += 1
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "zone": rec["zone"], "sid": rec["sid"], "month": rec["month"],
            "groups": len(rec["targets"]), "deleted": len(deleted),
            "failed": len(failed), "batches": batches,
            "paths": deleted, "failed_paths": failed,
            "method": "SHFileOperationW/FOF_ALLOWUNDO (系统回收站)",
        }
        self._append_log(record)
        return {"deleted": len(deleted), "failed": len(failed), "batches": batches,
                "failed_paths": failed, "log": str(DELETE_LOG),
                "stopped_early": bool(failed)}


# ------------------------------------------------------------------- HTML ---

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>微信图片 / 视频查看器</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--text:#1f2329;--sub:#6b7280;--accent:#2563eb;--danger:#dc2626}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:10px 20px}
h1{font-size:16px;margin:0 0 8px;font-weight:600}
.tabs{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-right:12px}
.tabs button{border:0;border-radius:0;padding:6px 16px;background:#fff}
.tabs button.on{background:var(--accent);color:#fff}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}
select,button,input{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text)}
button{cursor:pointer}button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
button:disabled{opacity:.45;cursor:not-allowed}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
button.danger{color:var(--danger);border-color:#f3c2c2}
.tag{color:var(--sub);font-size:12px}
.stat{font-weight:600;color:var(--accent)}
main{padding:14px 20px 40px}
.months{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.months button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.cell{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;position:relative;cursor:zoom-in}
.cell.sel{border-color:var(--accent);box-shadow:0 0 0 2px rgba(37,99,235,.18)}
.cell img{width:100%;height:140px;object-fit:cover;display:block;background:#eef0f3}
.cell .meta{padding:6px 8px;font-size:11px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .chk{position:absolute;top:6px;left:6px;width:18px;height:18px;cursor:pointer;accent-color:var(--accent)}
.cell .play{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}
.cell .play span{background:rgba(0,0,0,.55);color:#fff;border-radius:50%;width:34px;height:34px;display:flex;align-items:center;justify-content:center;font-size:14px}
.more{display:block;margin:20px auto;padding:8px 24px}
.empty{color:var(--sub);padding:40px;text-align:center}
#tip{display:none;position:fixed;z-index:30;max-width:460px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.16);padding:10px 12px;font-size:12px;line-height:1.7;pointer-events:none;word-break:break-all}
#tip b{color:var(--text)}#tip .k{color:var(--sub);display:inline-block;min-width:64px}
#box{display:none;position:fixed;inset:0;background:rgba(15,20,30,.92);z-index:20;align-items:center;justify-content:center;flex-direction:column}
#box.on{display:flex}#box img,#box video{max-width:94vw;max-height:84vh;object-fit:contain;background:#000}
#box .cap{color:#dbe2ea;margin-top:10px;font-size:12px}
#box .close{position:absolute;top:16px;right:20px;color:#fff;background:none;border:1px solid #6b7280;font-size:16px;padding:4px 12px}
#modal{display:none;position:fixed;inset:0;background:rgba(15,20,30,.6);z-index:40;align-items:center;justify-content:center;padding:20px}
#modal.on{display:flex}
.dialog{background:#fff;border-radius:10px;width:min(760px,96vw);max-height:88vh;display:flex;flex-direction:column;overflow:hidden}
.dialog h2{font-size:16px;margin:0;padding:14px 18px;border-bottom:1px solid var(--line)}
.dialog .body{padding:14px 18px;overflow:auto}
.dialog .foot{padding:12px 18px;border-top:1px solid var(--line);display:flex;gap:10px;justify-content:flex-end;align-items:center}
.warn{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;padding:10px 12px;border-radius:6px;font-weight:700;margin-bottom:12px}
.list{background:#f8f9fb;border:1px solid var(--line);border-radius:6px;max-height:220px;overflow:auto;padding:8px;font-family:Consolas,monospace;font-size:11px;line-height:1.6}
.result{white-space:pre-wrap;font-size:13px}
</style></head><body>
<header>
<h1>微信图片 / 视频查看器 <span class="tag" id="keyinfo"></span></h1>
<div class="bar">
  <div class="tabs"><button id="tab-image" class="on">图片分区</button><button id="tab-video">视频分区</button></div>
  <span class="tag" id="mode"></span>
</div>
<div class="bar" id="bar-image"><span class="tag">会话</span><select id="sid" style="min-width:400px"></select></div>
<div class="bar"><div class="months" id="months"></div></div>
<div class="bar">
  <label class="tag"><input type="checkbox" id="selall"> 全选本页</label>
  <span class="stat" id="selstat">已选 0 项 · 0 MB</span>
  <button id="btn-export" class="primary">导出勾选</button>
  <button id="btn-delete" class="danger">删除勾选（移入回收站）</button>
  <span class="tag" id="stat"></span>
</div>
</header>
<main><div class="grid" id="grid"></div><button class="more" id="more" style="display:none">加载更多</button><div class="empty" id="empty">正在加载…</div></main>
<div id="tip"></div>
<div id="box"><button class="close" onclick="closeBox()">关闭 ×</button><img id="big" style="display:none"><video id="vid" controls style="display:none" onerror="videoError()"></video><div class="cap" id="cap"></div></div>
<div id="modal"><div class="dialog"><h2 id="mtitle">确认操作</h2><div class="body" id="mbody"></div><div class="foot" id="mfoot"></div></div></div>
<script>
let ZONE='image',SID='',MONTH='',OFFSET=0,LIMIT=120,TOTAL=0,ALLOW=false,PENDING=null;
const SEL=new Set(), INFO={};
const $=id=>document.getElementById(id);
function fmt(n){return n>=1073741824?(n/1073741824).toFixed(2)+' GB':n>=1048576?(n/1048576).toFixed(1)+' MB':(n/1024).toFixed(0)+' KB'}
async function api(u,opt){const r=await fetch(u,opt);if(!r.ok)throw new Error((await r.text()).slice(0,300));return r.json()}
function post(u,obj){return api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)})}
function stub(){return{zone:ZONE,sid:SID,month:MONTH,bases:[...SEL]}}
function updateStat(){
  let n=0,s=0;for(const b of SEL){const it=ITEMS.find(x=>x.base===b);if(it){n++;s+=it.size}}
  $('selstat').textContent=`已选 ${n} 项 · ${fmt(s)}`;
  $('btn-export').disabled=n===0;$('btn-delete').disabled=n===0||!ALLOW;
}
let ITEMS=[];
async function init(){
  const k=await api('/api/status');ALLOW=k.allow_delete;
  $('keyinfo').textContent='密钥 '+k.key_desc+' · '+(ALLOW?'已启用删除（移入回收站）':'只读模式');
  $('mode').textContent=ALLOW?'删除需二次确认':'如需删除，重启时加 --allow-delete';
  const ss=await api('/api/sessions');
  $('sid').innerHTML=ss.map(s=>`<option value="${s.sid}">${s.last_date||'—'} → ${s.first_date||'—'} · ${s.size_mb} MB · ${s.file_count} 文件 · ${s.sid.slice(0,10)}…</option>`).join('');
  $('sid').onchange=()=>{SID=$('sid').value;showMonths()};
  if(ss.length){SID=ss[0].sid}
  $('tab-image').onclick=()=>switchZone('image');$('tab-video').onclick=()=>switchZone('video');
  showMonths();
}
function switchZone(z){
  ZONE=z;$('tab-image').classList.toggle('on',z==='image');$('tab-video').classList.toggle('on',z==='video');
  $('bar-image').style.display=z==='image'?'flex':'none';
  SEL.clear();ITEMS=[];showMonths();
}
async function showMonths(){
  const ms=ZONE==='image'?(SID?await api('/api/months?sid='+SID):[]):await api('/api/video_months');
  $('months').innerHTML=ms.map(m=>`<button data-m="${m}">${m}</button>`).join('');
  [...$('months').children].forEach(b=>b.onclick=()=>{MONTH=b.dataset.m;[...$('months').children].forEach(x=>x.classList.remove('on'));b.classList.add('on');load(true)});
  if(ms.length){MONTH=ms[ms.length-1];$('months').lastChild.classList.add('on');load(true)}else{reset('该分区没有内容')}
}
function reset(msg){$('grid').innerHTML='';ITEMS=[];$('more').style.display='none';$('empty').textContent=msg;$('empty').style.display='block';$('stat').textContent='';SEL.clear();updateStat()}
async function load(fresh){
  if(fresh){OFFSET=0;$('grid').innerHTML='';ITEMS=[];SEL.clear()}
  const u=ZONE==='image'?`/api/images?sid=${SID}&month=${MONTH}&offset=${OFFSET}&limit=${LIMIT}`:`/api/videos?month=${MONTH}&offset=${OFFSET}&limit=${LIMIT}`;
  const d=await api(u);TOTAL=d.total;ITEMS=ITEMS.concat(d.items);
  $('empty').style.display=TOTAL?'none':'block';
  if(!TOTAL){reset('该月份没有内容');return}
  d.items.forEach(it=>{
    const c=document.createElement('div');c.className='cell';c.dataset.base=it.base;
    const src=ZONE==='image'?`/api/img?sid=${SID}&month=${MONTH}&base=${encodeURIComponent(it.base)}&kind=thumb`:`/api/video_thumb?month=${MONTH}&base=${encodeURIComponent(it.base)}`;
    c.innerHTML=`<input type="checkbox" class="chk" ${SEL.has(it.base)?'checked':''}><img loading="lazy" src="${src}" alt=""><div class="meta">${it.base.slice(0,10)} · ${fmt(it.size)}${it.has_hd?' · 有原图':''}</div>${ZONE==='video'?'<div class="play"><span>▶</span></div>':''}`;
    c.querySelector('.chk').onclick=e=>{e.stopPropagation();if(e.target.checked)SEL.add(it.base);else SEL.delete(it.base);c.classList.toggle('sel',e.target.checked);updateStat()};
    c.onclick=()=>openBox(it);
    c.onmouseenter=e=>showTip(it.base,e);c.onmousemove=moveTip;c.onmouseleave=hideTip;
    $('grid').appendChild(c);
  });
  OFFSET+=d.items.length;
  $('stat').textContent=`${MONTH} · 共 ${TOTAL} 项 · 已显示 ${OFFSET} 项`;
  $('more').style.display=OFFSET<TOTAL?'block':'none';
  $('selall').checked=false;updateStat();
}
async function showTip(base,e){
  const key=ZONE+'|'+SID+'|'+MONTH+'|'+base;
  let m=INFO[key];
  if(!m){
    m=await api(`/api/info?zone=${ZONE}&sid=${SID}&month=${MONTH}&base=${encodeURIComponent(base)}`);INFO[key]=m;
  }
  const dim=m.width?`${m.width} × ${m.height}`:'未知';
  const dur=m.duration?`${m.duration} 秒`:'—';
  const rows=m.files.map(f=>`<div><span class="k">路径</span><b>${f.path}</b><br><span class="k">日期时间</span>${f.mtime_str}　<span class="k">大小</span>${fmt(f.size)}${f.nlink>1?'　<span style="color:#dc2626">硬链接 '+f.nlink+'</span>':''}</div>`).join('<hr style="border:0;border-top:1px solid #eee">');
  $('tip').innerHTML=`<div><span class="k">分区</span><b>${ZONE==='image'?'图片':'视频'}</b>　<span class="k">格式</span><b>${m.format}</b></div><div><span class="k">像素尺寸</span><b>${dim}</b>　<span class="k">时长</span>${dur}　<span class="k">合计</span>${fmt(m.total_size)}</div><hr style="border:0;border-top:1px solid #eee">${rows}`;
  $('tip').style.display='block';moveTip(e);
}
function moveTip(e){const t=$('tip');const x=Math.min(e.clientX+16,innerWidth-480),y=Math.min(e.clientY+16,innerHeight-260);t.style.left=Math.max(8,x)+'px';t.style.top=Math.max(8,y)+'px'}
function hideTip(){$('tip').style.display='none'}
function openBox(it){
  $('box').classList.add('on');
  if(ZONE==='image'){
    $('vid').style.display='none';$('vid').pause();$('big').style.display='block';
    $('big').src=`/api/img?sid=${SID}&month=${MONTH}&base=${encodeURIComponent(it.base)}&kind=full`;
  }else{
    $('big').style.display='none';$('vid').style.display='block';
    $('vid').src=`/api/video_stream?month=${MONTH}&base=${encodeURIComponent(it.base)}`;$('vid').play().catch(()=>{});
  }
  $('cap').textContent=`${it.base} · ${fmt(it.size)}`;
}
function closeBox(){$('box').classList.remove('on');$('big').src='';$('vid').pause();$('vid').src=''}
function videoError(){
  if(!$('box').classList.contains('on'))return;
  $('vid').style.display='none';$('big').style.display='block';
  $('big').src='/api/placeholder?text='+encodeURIComponent('不支持播放，需要解码器');
  $('cap').textContent='不支持播放，需要解码器';
}
function modal(title,body,foot){$('mtitle').textContent=title;$('mbody').innerHTML=body;$('mfoot').innerHTML='';foot.forEach(h=>{$('mfoot').appendChild(h)});$('modal').classList.add('on')}
function closeModal(){$('modal').classList.remove('on');PENDING=null}
function btn(text,cls,fn){const b=document.createElement('button');b.textContent=text;b.className=cls||'';b.onclick=fn;return b}
$('selall').onchange=e=>{
  [...$('grid').children].forEach(c=>{const b=c.dataset.base;if(e.target.checked)SEL.add(b);else SEL.delete(b);c.classList.toggle('sel',e.target.checked);c.querySelector('.chk').checked=e.target.checked});updateStat();
};
$('more').onclick=()=>load(false);
$('btn-export').onclick=async()=>{
  if(!SEL.size)return;
  try{
    const r=await post('/api/export',stub());
    modal('导出完成',`<div class="result">已导出 ${r.count} 个文件\nZIP：${r.path}\n大小：${fmt(r.bytes)}</div>`,[btn('下载 ZIP','primary',()=>location.href='/api/download?name='+encodeURIComponent(r.name)),btn('关闭','',closeModal)]);
  }catch(e){modal('导出失败',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
};
$('btn-delete').onclick=async()=>{
  if(!SEL.size||!ALLOW)return;
  try{
    const p=await post('/api/delete/preview',stub());PENDING=p.token;
    const list=p.files.map(f=>`${f.path}　(${fmt(f.size)})`).join('<br>');
    const body=`<div class="warn">⚠️ ${p.warning}</div>
      <div class="result">分组 <b>${p.group_count}</b> 项，实际文件 <b>${p.file_count}</b> 个，合计 <b>${fmt(p.total_size)}</b>${p.hardlinked_files?`<br><span style="color:#dc2626">其中 ${p.hardlinked_files} 个是硬链接文件，删除后不一定立刻释放空间</span>`:''}</div>
      <div class="list" style="margin:10px 0">${list}</div>
      <div>请输入 <b>${p.confirm_word}</b> 完成二次确认：<br><input id="cword" style="width:320px;margin-top:6px" autocomplete="off" placeholder="手工输入确认词"></div>`;
    modal('删除前确认（第一步：清单与风险）',body,[
      btn('取消','',closeModal),
      btn('第二步：移入回收站','danger',async()=>{
        const w=$('cword').value.trim();
        if(w!==p.confirm_word){alert('确认词不正确，未执行任何删除');return}
        try{
          const r=await post('/api/delete/commit',{token:p.token,confirm:w});
          load(true);
          modal('删除结果',`<div class="result">已移入回收站：${r.deleted} 个文件（${r.batches} 批）\n失败：${r.failed} 个${r.stopped_early?'\n已中止剩余批次':''}\n日志：${r.log}\n\n可从系统回收站还原。</div>`,[btn('关闭','',closeModal)]);
        }catch(e){modal('删除失败',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
      })
    ]);
  }catch(e){modal('无法预览删除',`<div class="result">${e.message}</div>`,[btn('关闭','',closeModal)])}
};
$('box').onclick=e=>{if(e.target.id==='box')closeBox()};
document.onkeydown=e=>{if(e.key==='Escape'){closeBox();closeModal()}};
init().catch(e=>reset('加载失败：'+e.message));
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    viewer: Viewer

    def log_message(self, fmt, *args):
        if "/api/img" not in (self.path or "") and "/api/video_" not in (self.path or ""):
            sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        v = self.viewer
        try:
            if u.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/status":
                self._json({"allow_delete": v.allow_delete, "key_desc": v.key_desc,
                            "xor_key": v.xor_key, "ffmpeg": str(v.ffmpeg) if v.ffmpeg else None,
                            "video_dir": str(v.video_dir)})
            elif u.path == "/api/sessions":
                self._json(v.sessions())
            elif u.path == "/api/months":
                self._json(v.months(q.get("sid", [""])[0]))
            elif u.path == "/api/images":
                total, items = v.images(q.get("sid", [""])[0], q.get("month", [""])[0],
                                        max(0, int(q.get("offset", ["0"])[0])),
                                        min(600, max(0, int(q.get("limit", ["120"])[0]))))
                self._json({"total": total, "items": items})
            elif u.path == "/api/img":
                data, mime = v.image_bytes(q.get("sid", [""])[0], q.get("month", [""])[0],
                                           q.get("base", [""])[0], q.get("kind", ["thumb"])[0])
                if data:
                    self._send(200, data, mime, cache=True)
                else:
                    hint = HINT_NEED_FFMPEG if not v.ffmpeg else HINT_NEED_TRANSCODE
                    self._send(200, placeholder_svg(hint), "image/svg+xml", cache=True)
            elif u.path == "/api/placeholder":
                text = q.get("text", [HINT_NEED_TRANSCODE])[0][:40]
                self._send(200, placeholder_svg(text), "image/svg+xml", cache=True)
            elif u.path == "/api/video_months":
                self._json(v.video_months())
            elif u.path == "/api/videos":
                total, items = v.videos(q.get("month", [""])[0],
                                        max(0, int(q.get("offset", ["0"])[0])),
                                        min(600, max(0, int(q.get("limit", ["120"])[0]))))
                self._json({"total": total, "items": items})
            elif u.path == "/api/video_thumb":
                data, mime = v.video_thumb(q.get("month", [""])[0], q.get("base", [""])[0])
                if data:
                    self._send(200, data, mime, cache=True)
                else:
                    self._send(200, placeholder_svg(HINT_NEED_COVER), "image/svg+xml", cache=True)
            elif u.path == "/api/video_stream":
                r = v.video_stream(q.get("month", [""])[0], q.get("base", [""])[0],
                                   self.headers.get("Range"))
                if not r:
                    self._send(404, b"no video", "text/plain")
                else:
                    partial = self.headers.get("Range") is not None
                    self._send(206 if partial else 200, r["data"], "video/mp4",
                               extra={"Accept-Ranges": "bytes",
                                      "Content-Range": f"bytes {r['start']}-{r['end']}/{r['size']}"})
            elif u.path == "/api/info":
                self._json(v.info(q.get("zone", ["image"])[0], q.get("sid", [""])[0],
                                  q.get("month", [""])[0], q.get("base", [""])[0]))
            elif u.path == "/api/download":
                name = q.get("name", [""])[0]
                p = EXPORT_DIR / name
                if not ZIP_RE.match(name) or not p.is_file():
                    self._send(404, b"not found", "text/plain")
                else:
                    self._send(200, p.read_bytes(), "application/zip",
                               extra={"Content-Disposition": f'attachment; filename="{name}"'})
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:
            self._send(500, f"error: {e}".encode("utf-8"), "text/plain; charset=utf-8")

    def do_POST(self):
        try:
            payload = self._body()
            v = self.viewer
            if self.path == "/api/export":
                self._json(v.make_export(payload))
            elif self.path == "/api/delete/preview":
                self._json(v.preview_delete(payload))
            elif self.path == "/api/delete/commit":
                self._json(v.commit_delete(payload.get("token", ""), payload.get("confirm", "")))
            else:
                self._send(404, b"not found", "text/plain")
        except (PermissionError, ValueError) as e:
            self._json({"error": str(e)}, 403)
        except Exception as e:
            self._send(500, f"error: {e}".encode("utf-8"), "text/plain; charset=utf-8")


# ------------------------------------------------------------------ 子命令 ---

def build_viewer(args) -> Viewer:
    return Viewer(
        data_root=resolve_data_root(args.data_root), account=args.account,
        sessions_csv=Path(args.sessions_csv),
        ffmpeg=Path(args.ffmpeg) if args.ffmpeg else None,
        allow_delete=bool(getattr(args, "allow_delete", False)),
    )


def cmd_probe(args):
    v = build_viewer(args)
    print("数据目录      :", v.data_root)
    print("账号          :", v.account)
    print("图片目录      :", v.attach)
    print("视频目录      :", v.video_dir)
    print("AES 密钥      :", v.aes_key.decode(), f"({v.key_desc})")
    print("XOR 密钥      :", v.xor_key, f"(0x{v.xor_key:02x})")
    print("ffmpeg        :", v.ffmpeg or "未找到（wxgf 图片无法预览）")
    print("删除功能      :", "已启用（仍需二次确认 + 回收站）" if v.allow_delete else "未启用（只读）")
    print("会话数        :", len(v.sessions()), " 视频月份数:", len(v.video_months()))
    vm = v.video_months()
    if vm:
        total, items = v.videos(vm[-1], 0, 3)
        print(f"视频抽样 {vm[-1]}: 共 {total} 个")
        for it in items:
            print("   ", it["base"][:12], it["date"], f"{it['size']/1048576:.1f} MB")
    print("只读校验      : probe 未写入任何微信文件")


def cmd_serve(args):
    v = build_viewer(args)
    Handler.viewer = v
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("微信图片/视频查看器已启动：", url)
    print("模式          :", "允许删除（需二次确认，移入系统回收站）" if v.allow_delete else "只读（默认）")
    print("密钥          :", v.key_desc, "| XOR:", hex(v.xor_key), "| ffmpeg:", v.ffmpeg or "无")
    print("图片目录      :", v.attach)
    print("视频目录      :", v.video_dir)
    print("导出目录      :", EXPORT_DIR, "（工作区，非微信目录）")
    print("删除日志      :", DELETE_LOG)
    print("按 Ctrl+C 停止。")
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


def cmd_export(args):
    v = build_viewer(args)
    out = assert_output_path(Path(args.out), wechat_roots=[v.data_root, DEFAULT_APPDATA])
    out.mkdir(parents=True, exist_ok=True)
    total, items = v.images(args.session, args.month, 0, 0)
    if args.limit > 0:
        items = items[: args.limit]
    print(f"导出 {args.session} / {args.month}：共 {total} 张，本次 {len(items)} 张 -> {out}")
    done = 0
    for it in items:
        data, mime = v.image_bytes(args.session, args.month, it["base"], "full")
        if data is None:
            continue
        (out / f"{args.month}_{it['base']}.{EXT_OF_MIME.get(mime, 'jpg')}").write_bytes(data)
        done += 1
    print(f"完成：{done} 张。微信目录未发生任何写入。")


def main():
    p = argparse.ArgumentParser(description="微信 4.x 图片/视频查看器（默认只读）")
    p.add_argument("--data-root", default=None,
                   help="微信数据根目录（默认自动扫描，并保存到当前文件夹的 wechat_data_root.dat）")
    p.add_argument("--account", default=None, help="账号目录名")
    p.add_argument("--sessions-csv", default=str(DEFAULT_CSV))
    p.add_argument("--ffmpeg", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="验证密钥、视频解析等")

    s = sub.add_parser("serve", help="启动本地看图网页")
    s.add_argument("--port", type=int, default=56789)
    s.add_argument("--open", action="store_true")
    s.add_argument("--allow-delete", action="store_true",
                   help="显式启用删除能力（仍需二次确认，文件移入系统回收站）")

    e = sub.add_parser("export", help="命令行导出某会话某月图片")
    e.add_argument("--session", required=True)
    e.add_argument("--month", required=True)
    e.add_argument("--out", default=str(DEFAULT_EXPORT))
    e.add_argument("--limit", type=int, default=0)

    args = p.parse_args()
    {"probe": cmd_probe, "serve": cmd_serve, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
