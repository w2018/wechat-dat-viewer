#!/usr/bin/env python
"""
wechat_dat_viewer.py — 微信 4.x 图片/视频查看器（零第三方依赖，双分区）v0.3.0

默认只读：
  * 微信目录只用 open(..., 'rb') 读取；看图/播放走内存 HTTP 响应，不落盘。
  * 不打开消息数据库、不解析聊天文本；HTTP 默认只绑定 127.0.0.1。

Web 访问（v0.3.0 起）：
  * 页面入口只挂在 /wx，/ 与 /index.html 返回 404、不跳转不提示；
  * 首次打开引导设置访问密码（>=6 位），PBKDF2 加盐哈希存同级 wechat_viewer_key.json；
  * 除登录/设置页外，所有 /api/* 都校验会话；
  * 同一 IP 30 秒内连续输错 3 次，封禁 10 分钟；计数与会话只在内存，重启清零。
  * 手机访问用 --host 0.0.0.0；首次设置密码仅允许本机(127.0.0.1)完成。

需要删除能力时必须显式加 --allow-delete，且：
  1) 先 POST /api/delete/preview 得到完整文件清单 + 一次性令牌；
  2) 前端展示警告与清单，要求手工输入确认词；
  3) POST /api/delete/commit 校验令牌 + 确认词后才分批(<=10)移入系统回收站；
  4) 每批验证、失败即停，全程写 JSONL 日志到工作区。
  删除的是媒体文件，绝不触碰数据库/配置；回收站可恢复。

用法：
  python wechat_dat_viewer.py probe
  python wechat_dat_viewer.py serve [--port 56789] [--host 0.0.0.0] [--allow-delete] [--open]
  python wechat_dat_viewer.py export --session <hash> --month 2026-09 --out <目录> [--limit 50]
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
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

from wechat_viewer_ui import auth_page, build_page  # noqa: E402

DEFAULT_CSV = TOOL_DIR / "sessions.csv"
DEFAULT_EXPORT = TOOL_DIR / "exports" / "images"
EXPORT_DIR = TOOL_DIR / "exports"
DELETE_LOG = TOOL_DIR / "delete_log.jsonl"
OP_LOG = TOOL_DIR / "operation_log.jsonl"         # 操作日志（含来源 IP），已被 .gitignore 排除
OP_LOG_MAX = 5000                                  # 超过这个行数自动截断，只留最近 5000 条
CLEAR_CONFIRM = "CLEAR_LOGS"                       # 清空操作日志的二次确认词
CONFIG_FILE = TOOL_DIR / "wechat_data_root.dat"   # 运行时生成，已被 .gitignore 排除
APP_VERSION = "0.3.1"
KEY_FILE = TOOL_DIR / "wechat_viewer_key.json"    # 访问密码（PBKDF2 哈希），已被 .gitignore 排除

SESSION_COOKIE = "wv_session"
SESSION_TTL = 12 * 3600        # 登录状态保留 12 小时
MAX_FAILS = 3                  # 30 秒内连续错误次数上限
FAIL_WINDOW = 30.0             # 错误计数滑动窗口（秒）
BAN_SECONDS = 600              # 封禁时长 10 分钟


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


# ------------------------------------------------------------------ 登录认证 ---

def is_mobile_ua(ua: str) -> bool:
    """按 UA 粗判手机/平板，用于选择移动端界面。"""
    return bool(re.search(r"(Mobile|Android|iPhone|iPod|iPad|HarmonyOS|MicroMessenger|Mobile Safari)",
                          ua or "", re.I))


def hash_password(password: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return {
        "algo": "pbkdf2_sha256",
        "iterations": 200_000,
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(dk).decode(),
    }


class Auth:
    """Web 访问密码：key 文件存 PBKDF2 哈希；会话与 IP 封禁只放内存。

    * 密码不落明文，key 文件仅程序目录可读（尽量 chmod 600）。
    * 30 秒滑动窗口内连续输错 3 次 → 该 IP 封禁 10 分钟。
    * 会话/封禁均不持久化，重启即清零（避免把自己永久锁死）。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.sessions: dict[str, float] = {}
        self.fails: dict[str, list[float]] = {}
        self.bans: dict[str, float] = {}
        self.record: dict | None = None
        self._load()

    # -- key 文件 ---------------------------------------------------------
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.record = None
            return
        if isinstance(raw, dict) and raw.get("hash") and raw.get("salt"):
            self.record = raw
        else:
            print(f"警告：{self.path} 格式不正确，已忽略（将要求重新设置密码）", file=sys.stderr)
            self.record = None

    @property
    def configured(self) -> bool:
        return self.record is not None

    def set_password(self, password: str) -> None:
        pwd = (password or "").strip()
        if len(pwd) < 6:
            raise ValueError("密码至少 6 位")
        rec = hash_password(pwd)
        rec["created"] = datetime.now().isoformat(timespec="seconds")
        assert_output_path(self.path)
        self.path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        with self.lock:
            self.record = rec
            self.sessions.clear()
            self.fails.clear()
            self.bans.clear()

    def verify(self, password: str) -> bool:
        rec = self.record
        if not rec:
            return False
        try:
            salt = base64.b64decode(rec["salt"])
            want = base64.b64decode(rec["hash"])
            it = int(rec.get("iterations") or 200_000)
        except (KeyError, ValueError, TypeError):
            return False
        got = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, it)
        return hmac.compare_digest(got, want)

    # -- 会话 -------------------------------------------------------------
    def new_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = time.time() + SESSION_TTL
        return token

    def valid_session(self, token: str | None) -> bool:
        if not token:
            return False
        with self.lock:
            exp = self.sessions.get(token)
            if not exp:
                return False
            if exp < time.time():
                self.sessions.pop(token, None)
                return False
            return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self.lock:
            self.sessions.pop(token, None)

    # -- 失败计数 / 封禁 ---------------------------------------------------
    def ban_left(self, ip: str) -> int:
        with self.lock:
            until = self.bans.get(ip, 0.0)
            left = int(until - time.time())
            if left > 0:
                return left
            self.bans.pop(ip, None)
            return 0

    def attempts_left(self, ip: str) -> int:
        now = time.time()
        with self.lock:
            arr = [t for t in self.fails.get(ip, []) if now - t <= FAIL_WINDOW]
            self.fails[ip] = arr
            return max(0, MAX_FAILS - len(arr))

    def note_failure(self, ip: str) -> int:
        """记录一次密码错误；触发封禁时返回封禁秒数，否则 0。"""
        now = time.time()
        with self.lock:
            arr = [t for t in self.fails.get(ip, []) if now - t <= FAIL_WINDOW]
            arr.append(now)
            self.fails[ip] = arr
            if len(arr) >= MAX_FAILS:
                self.bans[ip] = now + BAN_SECONDS
                self.fails[ip] = []
                return BAN_SECONDS
            return 0

    def clear_failure(self, ip: str) -> None:
        with self.lock:
            self.fails.pop(ip, None)
            self.bans.pop(ip, None)


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

# 删除时可按类型勾选：同一张图在微信目录里通常有 3 个文件
KIND_ORDER = ("main", "hd", "thumb")
KIND_LABEL = {
    ("image", "main"): ("普通图", ".dat · 微信压缩版"),
    ("image", "hd"): ("原图", "_h.dat · 高清原版"),
    ("image", "thumb"): ("缩略图", "_t.dat · 聊天列表预览"),
    ("video", "main"): ("视频", ".mp4 · 视频本体"),
    ("video", "thumb"): ("封面图", ".jpg · 视频首帧"),
}
# 缩略图默认不勾：体积小，删了只影响聊天列表里的小图
KIND_DEFAULT = {"main": True, "hd": True, "thumb": False}

# 操作日志的类型标签
OP_LABEL = {
    "login": "登录", "login_fail": "登录失败", "setup": "设置密码",
    "logout": "退出登录", "export": "导出", "delete": "删除", "clear": "清空日志",
}


def group_kind(item: dict) -> str:
    """一张卡片实际代表哪一类：有原图就算原图，其次普通图，最后缩略图。"""
    if item.get("has_hd"):
        return "hd"
    if item.get("has_main"):
        return "main"
    return "thumb"


def variant_of(path: Path, zone: str) -> str:
    """按文件名判定文件类型：main / hd / thumb。"""
    name = Path(path).name.lower()
    if zone == "video":
        return "main" if name.endswith(".mp4") else "thumb"
    stem = Path(path).stem.lower()
    if stem.endswith("_h"):
        return "hd"
    if stem.endswith("_t"):
        return "thumb"
    return "main"


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
        self._stats_cache: dict[str, dict] = {}
        self._scan_lock = threading.Lock()
        self._scan_state: dict = {"running": False, "done": 0, "total": 0,
                                  "elapsed": 0.0, "message": "", "finished": False,
                                  "error": ""}
        self._sessions_cache: list[dict] | None = None
        self._del_lock = threading.Lock()
        self._op_lock = threading.Lock()
        self._del_state: dict = {"running": False, "total": 0, "done": 0,
                                 "deleted": 0, "failed": 0, "bytes_total": 0,
                                 "bytes_done": 0, "current": "", "finished": False,
                                 "error": "", "result": None}
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

    def _scan_session_stats(self, d: Path) -> dict:
        """CSV 缺失时实时统计会话占用与文件数：只读 scandir 递归，结果缓存在内存。"""
        key = str(d)
        if key in self._stats_cache:
            return self._stats_cache[key]
        total = 0
        count = 0
        stack = [str(d)]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            elif e.is_file(follow_symlinks=False):
                                total += e.stat(follow_symlinks=False).st_size
                                count += 1
                        except OSError:
                            continue
            except OSError:
                continue
        res = {"size_bytes": total, "size_mb": round(total / 1048576, 1),
               "file_count": count}
        self._stats_cache[key] = res
        return res

    def sessions(self) -> list[dict]:
        if self._sessions_cache is not None:
            return self._sessions_cache
        out = []
        for d in self.attach.iterdir():
            if not d.is_dir() or not SID_RE.match(d.name):
                continue
            months = sorted(m.name for m in d.iterdir() if m.is_dir() and MONTH_RE.match(m.name))
            meta = self.sessions_meta.get(d.name)
            if not meta or meta.get("file_count", 0) <= 0:
                meta = self._scan_session_stats(d)
            first_date, last_date = self._session_dates(d, months)
            out.append({
                "sid": d.name,
                "size_bytes": int(meta.get("size_bytes", meta.get("size_mb", 0) * 1048576)),
                "size_mb": round(meta.get("size_mb", 0), 1),
                "file_count": meta.get("file_count", 0),
                "months": months,
                "first_date": first_date,
                "last_date": last_date,
            })
        # 下拉框按最新日期倒序（新 -> 旧），同日再按占用大小倒序
        out.sort(key=lambda x: (x["last_date"] or "", x["size_mb"]), reverse=True)
        return out

    # ------------------------------------------------------- 重新扫描/进度 ---
    def start_rescan(self) -> dict:
        """启动后台重新扫描：清空缓存，逐会话重算大小/文件数/日期并更新进度。"""
        with self._scan_lock:
            if self._scan_state["running"]:
                return {"started": False, "message": self._scan_state["message"]}
            self._scan_state = {"running": True, "done": 0, "total": 0,
                                "elapsed": 0.0, "message": "准备扫描…",
                                "finished": False, "error": ""}
        threading.Thread(target=self._rescan_worker, daemon=True).start()
        return {"started": True}

    def scan_status(self) -> dict:
        with self._scan_lock:
            return dict(self._scan_state)

    def _rescan_worker(self):
        t0 = time.time()
        try:
            dirs = sorted(d for d in self.attach.iterdir()
                          if d.is_dir() and SID_RE.match(d.name))
            total = len(dirs)
            with self._scan_lock:
                self._scan_state.update(total=total, message=f"正在扫描 0/{total} 个会话…")
            self._stats_cache.clear()
            self._meta_cache.clear()
            self.sessions_meta = {}
            out = []
            for i, d in enumerate(dirs, 1):
                months = sorted(m.name for m in d.iterdir()
                                if m.is_dir() and MONTH_RE.match(m.name))
                meta = self._scan_session_stats(d)
                first_date, last_date = self._session_dates(d, months)
                out.append({
                    "sid": d.name,
                    "size_bytes": int(meta.get("size_bytes", meta.get("size_mb", 0) * 1048576)),
                    "size_mb": round(meta.get("size_mb", 0), 1),
                    "file_count": meta.get("file_count", 0),
                    "months": months,
                    "first_date": first_date,
                    "last_date": last_date,
                })
                if i % 5 == 0 or i == total:
                    with self._scan_lock:
                        self._scan_state.update(
                            done=i, elapsed=round(time.time() - t0, 1),
                            message=f"正在扫描 {i}/{total} 个会话…")
            out.sort(key=lambda x: (x["last_date"] or "", x["size_mb"]), reverse=True)
            self._sessions_cache = out
            secs = round(time.time() - t0, 1)
            with self._scan_lock:
                self._scan_state.update(
                    running=False, finished=True, done=total, elapsed=secs,
                    message=f"扫描完成 · {total} 个会话 · {secs}s")
        except Exception as e:
            with self._scan_lock:
                self._scan_state.update(
                    running=False, finished=True, error=str(e),
                    message=f"扫描失败：{e}")

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
                 "has_main": "main" in g["variants"],
                 "has_hd": "hd" in g["variants"], "has_thumb": "thumb" in g["variants"]}
                for g in sorted(groups.values(), key=lambda x: x["base"])]

    def images(self, sid: str, month: str, offset: int, limit: int, kind: str = "all"):
        if not SID_RE.match(sid) or not MONTH_RE.match(month):
            return 0, []
        img = self.attach / sid / month / "Img"
        if not img.is_dir():
            return 0, []
        items = self._group_files(img)
        if kind in KIND_ORDER:                      # 按卡片上显示的标签筛，三者互斥
            items = [it for it in items if group_kind(it) == kind]
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
        # 逐候选回退：高清 -> 主图 -> 缩略图，取第一个能解出的。
        # 只有整组都解不出时才交给上层显示占位提示（wxgf 原图缺 ffmpeg 时
        # 通常仍能回退到明文 JPEG 缩略图，不应把整组判为不支持预览）。
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
            if self.ffmpeg is None and self.needs_ffmpeg(sid, month, base):
                fmt += " · 原图需 ffmpeg"
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
            metas = [dict(file_meta(p), kind=variant_of(p, zone)) for p in paths]
            out.append({"base": base, "files": metas,
                        "size": sum(m["size"] for m in metas),
                        "nlink_max": max(m["nlink"] for m in metas)})
        return out

    # ------------------------------------------------------------ 批量导出 ---
    def make_export(self, payload: dict, ip: str = "") -> dict:
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
        self.log_op("export", ip,
                    f"{zone} · {month} · 打包 {count} 个文件 → {name}",
                    files=[t["base"] for t in targets])
        return {"name": name, "path": str(zp), "count": count,
                "bytes": zp.stat().st_size, "dir": str(EXPORT_DIR)}

    # ------------------------------------------------------------ 删除链路 ---
    def _kind_summary(self, targets: list[dict], zone: str) -> list[dict]:
        """按文件类型汇总，供前端做勾选（默认不勾缩略图）。"""
        agg: dict[str, dict] = {}
        for t in targets:
            for f in t["files"]:
                k = f.get("kind", "main")
                a = agg.setdefault(k, {"kind": k, "count": 0, "size": 0})
                a["count"] += 1
                a["size"] += f["size"]
        out = []
        for k in KIND_ORDER:
            if k not in agg:
                continue
            name, desc = KIND_LABEL.get((zone, k), (k, ""))
            a = agg[k]
            out.append({"kind": k, "label": name, "desc": desc,
                        "count": a["count"], "size": a["size"],
                        "default": KIND_DEFAULT.get(k, True)})
        return out

    def preview_delete(self, payload: dict) -> dict:
        if not self.allow_delete:
            raise PermissionError("删除功能未启用：启动服务时需加 --allow-delete")
        targets = self.resolve_targets(payload)
        if not targets:
            raise ValueError("没有可删除的文件")
        files = [f for t in targets for f in t["files"]]
        zone = payload["zone"]
        token = secrets.token_urlsafe(24)
        self._tokens[token] = {"ts": time.time(), "targets": targets,
                              "zone": zone, "month": payload["month"],
                              "sid": payload.get("sid", "")}
        return {
            "token": token, "confirm_word": CONFIRM_WORD,
            "group_count": len(targets), "file_count": len(files),
            "total_size": sum(f["size"] for f in files),
            "hardlinked_files": sum(1 for f in files if f["nlink"] > 1),
            "kinds": self._kind_summary(targets, zone),
            "files": files,
            "warning": "此操作非常危险，可能导致不可逆的数据丢失！文件将被移入系统回收站；"
                       "微信聊天记录中的对应图片/视频会失效，且微信可能重新下载。",
        }

    def _append_log(self, record: dict) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        with DELETE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------ 操作日志 ---
    def log_op(self, action: str, ip: str = "", detail: str = "",
               files: list[str] | None = None, ok: bool = True) -> None:
        """记一条操作日志：时间、来源 IP、类型、涉及文件（只留文件名，最多 20 个）。"""
        names = [Path(p).name for p in (files or [])][:20]
        rec = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "action": action, "label": OP_LABEL.get(action, action),
               "ip": ip or "-", "detail": detail,
               "count": len(files or []), "files": names, "ok": bool(ok)}
        try:
            with self._op_lock:
                with OP_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if OP_LOG.stat().st_size > 2 * 1024 * 1024:   # 防无限膨胀
                    lines = OP_LOG.read_text(encoding="utf-8").splitlines()[-OP_LOG_MAX:]
                    OP_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"  操作日志写入失败：{e}\n")

    def read_logs(self, limit: int = 200) -> dict:
        try:
            limit = max(1, min(int(limit or 200), 1000))
        except (TypeError, ValueError):
            limit = 200
        try:
            lines = OP_LOG.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        items = []
        for ln in reversed(lines[-limit:]):       # 倒序：最新的在最上面
            try:
                items.append(json.loads(ln))
            except ValueError:
                continue
        return {"total": len(lines), "items": items, "path": str(OP_LOG)}

    def clear_logs(self, confirm: str, ip: str = "") -> dict:
        if confirm != CLEAR_CONFIRM:
            raise ValueError("确认词不正确，未清空任何日志")
        try:
            removed = len(OP_LOG.read_text(encoding="utf-8").splitlines())
        except OSError:
            removed = 0
        OP_LOG.write_text("", encoding="utf-8")
        self.log_op("clear", ip, f"清空 {removed} 条操作记录")   # 清空动作本身也留痕
        return {"cleared": removed, "path": str(OP_LOG)}

    def commit_delete(self, token: str, confirm: str, kinds=None, ip: str = "") -> dict:
        """校验通过后启动后台线程分批删除，前端轮询 /api/delete/status 看进度。"""
        if not self.allow_delete:
            raise PermissionError("删除功能未启用")
        rec = self._tokens.get(token)
        if not rec or time.time() - rec["ts"] > TOKEN_TTL:
            self._tokens.pop(token, None)
            raise ValueError("确认令牌无效或已过期，请重新预览")
        if confirm != CONFIRM_WORD:
            raise ValueError("二次确认未通过：确认词不正确")
        with self._del_lock:
            if self._del_state["running"]:
                raise ValueError("已有删除任务在执行，请等它跑完")
            wanted = {k for k in (kinds or []) if k in KIND_ORDER}
            if not wanted:
                # 未指定类型时按默认（原图 + 普通图），绝不顺手带上缩略图
                wanted = {k for k, on in KIND_DEFAULT.items() if on}
            plan = []
            for t in rec["targets"]:
                for f in t["files"]:
                    if f.get("kind", "main") in wanted:
                        plan.append(f)
            if not plan:
                raise ValueError("没有勾选任何要删除的文件类型")
            self._tokens.pop(token, None)
            self._del_state = {
                "running": True, "total": len(plan), "done": 0,
                "deleted": 0, "failed": 0,
                "bytes_total": sum(f["size"] for f in plan), "bytes_done": 0,
                "current": "", "finished": False, "error": "", "result": None,
                "kinds": sorted(wanted),
            }
        threading.Thread(target=self._delete_worker,
                         args=(plan, rec, sorted(wanted), ip), daemon=True).start()
        return {"started": True, "total": len(plan),
                "bytes_total": self._del_state["bytes_total"]}

    def delete_status(self) -> dict:
        with self._del_lock:
            return dict(self._del_state)

    def _delete_worker(self, plan: list[dict], rec: dict, kinds: list[str], ip: str = "") -> None:
        deleted: list[str] = []
        failed: list[str] = []
        batches = 0
        paths = [f["path"] for f in plan]
        size_of = {f["path"]: f["size"] for f in plan}
        for i in range(0, len(paths), BATCH_SIZE):
            batch = paths[i:i + BATCH_SIZE]
            try:
                # 提交前再校验一次，防止清单生成后路径被替换
                batch = [str(self._safe_media(Path(x))) for x in batch]
                with self._del_lock:
                    self._del_state["current"] = Path(batch[0]).name
                r = recycle_batch([Path(x) for x in batch])
                still = [x for x in batch if Path(x).exists()]
                ok = [x for x in batch if x not in still]
                deleted.extend(ok)
                with self._del_lock:
                    self._del_state["deleted"] = len(deleted)
                    self._del_state["done"] = len(deleted) + len(failed)
                    self._del_state["bytes_done"] += sum(size_of.get(x, 0) for x in ok)
                if not r["ok"] or still:
                    failed.extend(still or batch)
                    with self._del_lock:
                        self._del_state["failed"] = len(failed)
                        self._del_state["done"] = len(deleted) + len(failed)
                    break
                batches += 1
            except Exception as e:  # 单批异常也要如实记录，不能静默
                failed.extend(batch)
                with self._del_lock:
                    self._del_state["failed"] = len(failed)
                    self._del_state["error"] = str(e)
                break
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "zone": rec["zone"], "sid": rec["sid"], "month": rec["month"],
            "kinds": kinds,
            "groups": len(rec["targets"]), "deleted": len(deleted),
            "failed": len(failed), "batches": batches,
            "paths": deleted, "failed_paths": failed,
            "method": "SHFileOperationW/FOF_ALLOWUNDO (系统回收站)",
        }
        self._append_log(record)
        kind_txt = "、".join(KIND_LABEL.get((rec["zone"], k), (k, ""))[0] for k in kinds)
        self.log_op("delete", ip,
                    f"{rec['month']} · {kind_txt} · 移入回收站 {len(deleted)} 个文件"
                    + (f"（失败 {len(failed)} 个）" if failed else ""),
                    files=deleted, ok=not failed)
        with self._del_lock:
            self._del_state.update({
                "running": False, "finished": True, "current": "",
                "done": len(deleted) + len(failed),
                "deleted": len(deleted), "failed": len(failed),
                "bytes_done": sum(size_of.get(x, 0) for x in deleted),
                "result": {"deleted": len(deleted), "failed": len(failed),
                           "batches": batches, "failed_paths": failed,
                           "log": str(DELETE_LOG), "stopped_early": bool(failed),
                           "kinds": kinds},
            })


# ------------------------------------------------------------------- HTML ---



class Handler(BaseHTTPRequestHandler):
    viewer: Viewer
    auth: Auth

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

    def _json(self, obj, code: int = 200, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", extra=extra)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    # -- 认证辅助 ---------------------------------------------------------
    def _ip(self) -> str:
        return self.client_address[0]

    def _is_local(self) -> bool:
        return self._ip() in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _cookies(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, val = part.split("=", 1)
                out[k.strip()] = val.strip()
        return out

    def _token(self) -> str | None:
        return self._cookies().get(SESSION_COOKIE)

    def _authed(self) -> bool:
        return self.auth.valid_session(self._token())

    def _guard(self) -> bool:
        """未登录时直接回 401 并返回 True；已登录返回 False。"""
        if self._authed():
            return False
        if not self.auth.configured:
            self._json({"error": "尚未设置访问密码", "need_setup": True}, 401)
        else:
            self._json({"error": "未登录或登录已过期", "need_login": True}, 401)
        return True

    def _set_cookie(self, token: str, max_age: int = SESSION_TTL) -> dict:
        return {"Set-Cookie": f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"}

    def _do_login(self) -> None:
        payload = self._body()
        ip = self._ip()
        left = self.auth.ban_left(ip)
        if left > 0:
            self.viewer.log_op("login_fail", ip, f"封禁期内尝试登录（剩余 {left} 秒）", ok=False)
            self._json({"error": f"尝试次数过多，请在 {left // 60} 分 {left % 60} 秒后重试",
                        "retry_after": left}, 429)
            return
        if self.auth.verify(str(payload.get("password", ""))):
            self.auth.clear_failure(ip)
            self.viewer.log_op("login", ip, "密码验证通过")
            token = self.auth.new_session()
            self._json({"ok": True}, 200, self._set_cookie(token))
            return
        ban = self.auth.note_failure(ip)
        if ban:
            self.viewer.log_op("login_fail", ip, "30 秒内连续输错 3 次，已封禁 10 分钟", ok=False)
            self._json({"error": "30 秒内连续输错 3 次，已禁止该 IP 访问 10 分钟", "retry_after": ban}, 429)
        else:
            n = self.auth.attempts_left(ip)
            self.viewer.log_op("login_fail", ip, f"密码错误（还可尝试 {n} 次）", ok=False)
            self._json({"error": f"密码错误，还可尝试 {n} 次", "attempts_left": n}, 401)

    def _do_setup(self) -> None:
        payload = self._body()
        if not self._is_local():
            self._json({"error": "首次设置密码需在运行程序的电脑上操作（127.0.0.1）"}, 403)
            return
        if self.auth.configured:
            self._json({"error": "密码已存在，请直接登录；忘记密码可删除 key 文件后重启"}, 409)
            return
        pw = str(payload.get("password", ""))
        confirm = str(payload.get("confirm", "") or pw)
        if len(pw.strip()) < 6:
            self._json({"error": "密码至少 6 位"}, 400)
            return
        if pw != confirm:
            self._json({"error": "两次输入的密码不一致"}, 400)
            return
        self.auth.set_password(pw)
        self.viewer.log_op("setup", self._ip(), "设置访问密码")
        token = self.auth.new_session()
        print(f"已设置访问密码（{self.auth.path}）", flush=True)
        self._json({"ok": True}, 200, self._set_cookie(token))

    def _do_logout(self) -> None:
        self.auth.revoke(self._token())
        self.viewer.log_op("logout", self._ip(), "退出登录")
        self._json({"ok": True}, 200, self._set_cookie("", 0))

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        v = self.viewer
        try:
            if u.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif u.path == "/":
                # 入口只认 /wx：根路径不跳转、不提示，当作不存在
                self._send(404, b"not found", "text/plain")
            elif u.path in ("/wx", "/wx/"):
                mobile = is_mobile_ua(self.headers.get("User-Agent", ""))
                if not self.auth.configured:
                    body = auth_page(mobile, True, 0, self._is_local())
                elif not self._authed():
                    body = auth_page(mobile, False, self.auth.ban_left(self._ip()))
                else:
                    body = build_page(mobile)
                self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path.startswith("/api/") and self._guard():
                pass
            elif u.path == "/api/status":
                self._json({"allow_delete": v.allow_delete, "key_desc": v.key_desc,
                            "xor_key": v.xor_key, "ffmpeg": str(v.ffmpeg) if v.ffmpeg else None,
                            "video_dir": str(v.video_dir)})
            elif u.path == "/api/rescan/status":
                self._json(v.scan_status())
            elif u.path == "/api/delete/status":
                self._json(v.delete_status())
            elif u.path == "/api/logs":
                data = v.read_logs(q.get("limit", ["200"])[0])
                data["ip"] = self._ip()
                data["clear_word"] = CLEAR_CONFIRM
                self._json(data)
            elif u.path == "/api/sessions":
                self._json(v.sessions())
            elif u.path == "/api/months":
                self._json(v.months(q.get("sid", [""])[0]))
            elif u.path == "/api/images":
                total, items = v.images(q.get("sid", [""])[0], q.get("month", [""])[0],
                                        max(0, int(q.get("offset", ["0"])[0])),
                                        min(600, max(0, int(q.get("limit", ["120"])[0]))),
                                        q.get("kind", ["all"])[0])
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
            path = urlparse(self.path).path
            if path == "/api/auth/login":
                self._do_login()
                return
            if path == "/api/auth/setup":
                self._do_setup()
                return
            if path == "/api/auth/logout":
                self._do_logout()
                return
            if self._guard():
                return
            payload = self._body()
            v = self.viewer
            if path == "/api/rescan":
                self._json(v.start_rescan())
            elif path == "/api/export":
                self._json(v.make_export(payload, self._ip()))
            elif path == "/api/delete/preview":
                self._json(v.preview_delete(payload))
            elif path == "/api/delete/commit":
                self._json(v.commit_delete(payload.get("token", ""),
                                           payload.get("confirm", ""),
                                           payload.get("kinds") or [],
                                           self._ip()))
            elif path == "/api/logs/clear":
                self._json(v.clear_logs(str(payload.get("confirm", "")), self._ip()))
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
    auth = Auth(KEY_FILE)
    Handler.auth = auth
    host = getattr(args, "host", None) or "127.0.0.1"
    srv = ThreadingHTTPServer((host, args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/wx"
    loopback = host in ("127.0.0.1", "localhost", "::1")
    print(f"微信图片/视频查看器 v{APP_VERSION} 已启动：", url)
    print("入口路径      : /wx（根路径不跳转、不提示，必须手动输入 /wx）")
    print("监听地址      :", f"{host}:{args.port}", "" if loopback else "（已对外开放）")
    if not loopback:
        print("手机/局域网   :", f"http://<本机局域网 IP>:{args.port}/wx")
        print("安全提示      : 所有接口（含图片/视频）均需登录；首次设置密码请在本机浏览器完成。")
    print("访问密码      :", "已设置" if auth.configured
          else f"未设置 —— 首次打开 {url} 会引导设置（至少 6 位）")
    print("登录保护      :", f"30 秒内连续输错 {MAX_FAILS} 次，禁止该 IP {BAN_SECONDS // 60} 分钟")
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
    p.add_argument("--version", action="version", version=f"wechat-dat-viewer {APP_VERSION}")
    p.add_argument("--data-root", default=None,
                   help="微信数据根目录（默认自动扫描，并保存到当前文件夹的 wechat_data_root.dat）")
    p.add_argument("--account", default=None, help="账号目录名")
    p.add_argument("--sessions-csv", default=str(DEFAULT_CSV))
    p.add_argument("--ffmpeg", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="验证密钥、视频解析等")

    s = sub.add_parser("serve", help="启动本地看图网页")
    s.add_argument("--port", type=int, default=56789)
    s.add_argument("--host", default="127.0.0.1",
                   help="监听地址，默认 127.0.0.1（仅本机）；手机访问用 0.0.0.0 或本机局域网 IP")
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
