"""配置、会话与统计数据的持久化。"""
import json
import os
import threading
import time
import uuid
from pathlib import Path

APP_NAME = "AiCodeMac"
ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    p = os.environ.get("AICODE_DATA")
    if p:
        d = Path(p).expanduser()
    else:
        d = Path.home() / "Library" / "Application Support" / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA = data_dir()
CONFIG_FILE = DATA / "config.json"
SESSIONS = DATA / "sessions"
CHECKPOINTS = DATA / "checkpoints"
STATS = DATA / "stats.jsonl"
SESSIONS.mkdir(parents=True, exist_ok=True)
CHECKPOINTS.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()

DEFAULT_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "protocol": "openai",
        "baseUrl": "https://api.openai.com/v1",
        "keys": [],
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "input": 2.5, "output": 10},
            {"id": "gpt-4o-mini", "name": "GPT-4o mini", "input": 0.15, "output": 0.6},
        ],
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "protocol": "anthropic",
        "baseUrl": "https://api.anthropic.com",
        "keys": [],
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "input": 3, "output": 15},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "input": 0.8, "output": 4},
        ],
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "protocol": "gemini",
        "baseUrl": "https://generativelanguage.googleapis.com",
        "keys": [],
        "models": [
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "input": 1.25, "output": 10},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "input": 0.3, "output": 2.5},
        ],
    },
]

DEFAULT_CONFIG = {
    "version": 1,
    "language": "zh",
    "theme": "dark",
    "accent": "#4f8cff",
    "fontSize": 14,
    "providers": DEFAULT_PROVIDERS,
    "active": {"providerId": "", "model": ""},
    "mode": "build",
    "workspace": str(Path.home()),
    "permissions": {
        "run_shell": "ask",
        "write_file": "ask",
        "edit_file": "ask",
        "open_terminal": "ask",
        "mcp_call": "ask",
        "web_fetch": "allow",
    },
    "alwaysAllow": [],
    "systemPrompt": "",
    "proxy": "",
    "mcpServers": {},
    "keyRotation": "sequential",
    "contextLimit": 128000,
    "compressRatio": 0.6,
    "recentWorkspaces": [],
    "skillsDirs": [],
}


def _merge(base, cur):
    if isinstance(base, dict) and isinstance(cur, dict):
        out = dict(base)
        for k, v in cur.items():
            out[k] = _merge(base.get(k), v) if k in base else v
        return out
    return cur


def load_config() -> dict:
    with _lock:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if CONFIG_FILE.exists():
            try:
                cfg = _merge(cfg, json.loads(CONFIG_FILE.read_text("utf-8")))
            except Exception:
                pass
        return cfg


def save_config(cfg: dict):
    with _lock:
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(CONFIG_FILE)


def public_config(cfg: dict) -> dict:
    """返回给前端的配置：密钥打码，同时给出是否已配置。"""
    out = json.loads(json.dumps(cfg))
    for p in out.get("providers", []):
        p["hasKey"] = any(bool(k.strip()) for k in p.get("keys", []))
        p["keys"] = ["••••" + k[-4:] if len(k) > 4 else "••••" for k in p.get("keys", []) if k]
    return out


def session_path(sid: str) -> Path:
    return SESSIONS / (sid + ".json")


def list_sessions():
    items = []
    for f in SESSIONS.glob("*.json"):
        try:
            s = json.loads(f.read_text("utf-8"))
            items.append({
                "id": s.get("id"),
                "title": s.get("title") or "新会话",
                "createdAt": s.get("createdAt", 0),
                "updatedAt": s.get("updatedAt", 0),
                "messageCount": len(s.get("messages", [])),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x.get("updatedAt", 0), reverse=True)
    return items


def new_session(title="新会话", workspace=None) -> dict:
    sid = uuid.uuid4().hex[:12]
    s = {
        "id": sid,
        "title": title,
        "createdAt": int(time.time() * 1000),
        "updatedAt": int(time.time() * 1000),
        "workspace": workspace or "",
        "messages": [],
        "todos": [],
        "checkpoints": [],
    }
    save_session(s)
    return s


def load_session(sid: str) -> dict:
    p = session_path(sid)
    if not p.exists():
        raise FileNotFoundError(sid)
    return json.loads(p.read_text("utf-8"))


def save_session(s: dict):
    s["updatedAt"] = int(time.time() * 1000)
    with _lock:
        p = session_path(s["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False), "utf-8")
        tmp.replace(p)


def delete_session(sid: str):
    p = session_path(sid)
    if p.exists():
        p.unlink()


def record_stats(rec: dict):
    rec = dict(rec)
    rec["ts"] = int(time.time() * 1000)
    with _lock:
        with STATS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_stats():
    rows = []
    if STATS.exists():
        for line in STATS.read_text("utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows
