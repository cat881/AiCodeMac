#!/usr/bin/env python3
"""AiCode for macOS 本地服务：静态界面 + JSON API + SSE。"""
import argparse
import base64
import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent  # noqa: E402
import checkpoints  # noqa: E402
import fsops  # noqa: E402
import gitops  # noqa: E402
import mcp  # noqa: E402
import providers  # noqa: E402
import store  # noqa: E402
import terminal  # noqa: E402
import tools  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"
VERSION = "1.0.0"

TERMS = terminal.TermManager()
MCPM = mcp.McpManager()
PENDING = {}
CANCEL = {}
_pending_lock = threading.Lock()


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def make_approver(emit):
    def request_approval(tool_name, summary, detail=""):
        aid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        with _pending_lock:
            PENDING[aid] = {"event": ev, "allowed": False, "always": False, "ts": time.time()}
        emit({"type": "approval", "id": aid, "tool": tool_name, "summary": summary, "detail": detail})
        ok = ev.wait(300)
        with _pending_lock:
            rec = PENDING.pop(aid, {"allowed": False, "always": False})
        if not ok:
            emit({"type": "notice", "text": "授权请求超时，已跳过该操作。"})
            return False
        return bool(rec.get("allowed"))
    return request_approval


class Handler(BaseHTTPRequestHandler):
    server_version = "AiCodeMac/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("AICODE_DEBUG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- helpers
    def send_json(self, obj, code=200):
        body = json_bytes(obj)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error(self, msg, code=400):
        self.send_json({"ok": False, "error": str(msg)}, code)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("请求体不是合法 JSON")

    def query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def sse_send(self, obj):
        try:
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    # ---------------------------------------------------------------- routing
    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path.startswith("/api/"):
                return self.api_get(path)
            return self.serve_static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            try:
                self.error("服务器内部错误", 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if not path.startswith("/api/"):
                return self.error("Not Found", 404)
            return self.api_post(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as e:
            self.error(e)
        except FileNotFoundError as e:
            self.error("未找到: %s" % e, 404)
        except Exception:
            traceback.print_exc()
            try:
                self.error("服务器内部错误", 500)
            except Exception:
                pass

    def do_DELETE(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            m = re.match(r"^/api/session/([\w-]+)$", path)
            if m:
                store.delete_session(m.group(1))
                return self.send_json({"ok": True})
            return self.error("Not Found", 404)
        except Exception:
            traceback.print_exc()
            self.error("服务器内部错误", 500)

    # ---------------------------------------------------------------- static
    def serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = urllib.parse.unquote(path.lstrip("/"))
        target = (WEB / rel).resolve()
        try:
            target.relative_to(WEB.resolve())
        except ValueError:
            return self.error("Forbidden", 403)
        if not target.exists() or target.is_dir():
            target = WEB / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---------------------------------------------------------------- GET API
    def api_get(self, path):
        cfg = store.load_config()
        q = self.query()

        if path == "/api/health":
            return self.send_json({"ok": True, "version": VERSION, "pid": os.getpid()})
        if path == "/api/state":
            ws = cfg.get("workspace") or str(Path.home())
            return self.send_json({
                "ok": True, "version": VERSION,
                "config": store.public_config(cfg),
                "sessions": store.list_sessions(),
                "terminals": TERMS.list(),
                "mcp": MCPM.status(),
                "workspace": ws,
                "home": str(Path.home()),
            })
        if path == "/api/session/new":
            s = store.new_session(workspace=cfg.get("workspace"))
            return self.send_json({"ok": True, "session": s})
        m = re.match(r"^/api/session/([\w-]+)$", path)
        if m:
            return self.send_json({"ok": True, "session": store.load_session(m.group(1))})
        if path == "/api/stats":
            return self.send_json({"ok": True, "rows": store.load_stats()})
        if path == "/api/checkpoints":
            sid = (q.get("session") or [""])[0]
            return self.send_json({"ok": True, "items": checkpoints.list_checkpoints(sid)})

        # 文件系统
        ws = cfg.get("workspace") or str(Path.home())
        if path == "/api/fs/tree":
            rel = (q.get("path") or ["."])[0]
            depth = int((q.get("depth") or ["3"])[0])
            return self.send_json({"ok": True, "tree": fsops.tree(ws, rel, depth)})
        if path == "/api/fs/read":
            return self.send_json({"ok": True, "file": fsops.read_text(ws, (q.get("path") or [""])[0])})
        if path == "/api/fs/search":
            rows = fsops.search(ws, (q.get("q") or [""])[0], (q.get("glob") or [""])[0])
            return self.send_json({"ok": True, "results": rows})

        # Git
        if path.startswith("/api/git/"):
            sub = path[len("/api/git/"):]
            if not gitops.is_repo(ws):
                return self.send_json({"ok": True, "repo": False})
            if sub == "status":
                return self.send_json({"ok": True, **gitops.status(ws)})
            if sub == "log":
                return self.send_json({"ok": True, "commits": gitops.log(ws)})
            if sub == "branches":
                return self.send_json({"ok": True, "branches": gitops.branches(ws)})
            if sub == "tags":
                return self.send_json({"ok": True, "tags": gitops.tags(ws)})
            if sub == "diff":
                r = gitops.diff(ws, (q.get("path") or [""])[0], (q.get("staged") or ["0"])[0] == "1",
                                (q.get("commit") or [""])[0])
                return self.send_json({"ok": True, **r})
            if sub == "user":
                return self.send_json({"ok": True, "user": gitops.current_user(ws)})
        # 终端
        if path == "/api/terms":
            return self.send_json({"ok": True, "items": TERMS.list()})
        if path == "/api/term/stream":
            return self.term_stream((q.get("id") or [""])[0], int((q.get("offset") or ["0"])[0]))
        # MCP
        if path == "/api/mcp/status":
            return self.send_json({"ok": True, "servers": MCPM.status()})
        if path == "/api/backup/export":
            data = {
                "app": "AiCodeMac", "version": VERSION,
                "exportedAt": int(time.time() * 1000),
                "config": cfg,
                "sessions": [],
            }
            for it in store.list_sessions():
                try:
                    data["sessions"].append(store.load_session(it["id"]))
                except Exception:
                    pass
            body = json_bytes(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="aicode-backup.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self.error("Not Found", 404)

    # ---------------------------------------------------------------- POST API
    def api_post(self, path):
        cfg = store.load_config()
        b = self.body()

        if path == "/api/config":
            newcfg = b.get("config") or {}
            old_by_id = {p.get("id"): p for p in cfg.get("providers", [])}
            for p in newcfg.get("providers", []):
                old = old_by_id.get(p.get("id"), {})
                old_keys = old.get("keys") or []
                keys = []
                for i, k in enumerate(p.get("keys") or []):
                    if isinstance(k, str) and k.startswith("••••"):
                        keys.append(old_keys[i] if i < len(old_keys) else "")
                    else:
                        keys.append(k)
                p["keys"] = [k for k in keys if isinstance(k, str)]
            merged = dict(cfg)
            merged.update({k: v for k, v in newcfg.items() if k != "providers"})
            merged["providers"] = newcfg.get("providers", cfg.get("providers", []))
            store.save_config(merged)
            if merged.get("workspace") != cfg.get("workspace"):
                recent = [w for w in (merged.get("recentWorkspaces") or []) if w != merged["workspace"]]
                merged["recentWorkspaces"] = ([merged["workspace"]] + recent)[:8]
                store.save_config(merged)
            if "mcpServers" in newcfg:
                MCPM.reload(merged.get("mcpServers") or {})
            return self.send_json({"ok": True, "config": store.public_config(merged)})

        if path == "/api/provider/test":
            pid = b.get("providerId")
            prov = next((p for p in cfg.get("providers", []) if p.get("id") == pid), None)
            if not prov:
                return self.error("供应商不存在")
            model = b.get("model") or (prov.get("models") or [{}])[0].get("id")
            try:
                out = providers.simple_complete(prov, model, "只回复两个字：可用", "ping",
                                                proxy=cfg.get("proxy", ""))
                return self.send_json({"ok": True, "reply": out[:100]})
            except Exception as e:
                return self.send_json({"ok": False, "error": str(e)})

        if path == "/api/workspace":
            target = b.get("path") or ""
            if target == "__pick__":
                target = pick_folder()
                if not target:
                    return self.send_json({"ok": False, "cancelled": True})
            p = Path(target).expanduser()
            if not p.is_dir():
                return self.error("目录不存在: %s" % target)
            cfg["workspace"] = str(p.resolve())
            recent = [w for w in (cfg.get("recentWorkspaces") or []) if w != cfg["workspace"]]
            cfg["recentWorkspaces"] = ([cfg["workspace"]] + recent)[:8]
            store.save_config(cfg)
            return self.send_json({"ok": True, "workspace": cfg["workspace"]})

        if path == "/api/sessions":
            return self.send_json({"ok": True, "sessions": store.list_sessions()})
        if path == "/api/session/new":
            s = store.new_session(title=b.get("title") or "新会话", workspace=cfg.get("workspace"))
            return self.send_json({"ok": True, "session": s})
        m = re.match(r"^/api/session/([\w-]+)$", path)
        if m:
            s = store.load_session(m.group(1))
            for k in ("title", "workspace", "todos", "messages"):
                if k in b:
                    s[k] = b[k]
            store.save_session(s)
            return self.send_json({"ok": True, "session": s})

        if path == "/api/chat":
            return self.chat(b, cfg)
        if path == "/api/stop":
            sid = b.get("sessionId")
            ev = CANCEL.get(sid)
            if ev:
                ev.set()
            return self.send_json({"ok": True})
        if path == "/api/approve":
            aid = b.get("id")
            with _pending_lock:
                rec = PENDING.get(aid)
            if not rec:
                return self.error("授权请求已失效")
            rec["allowed"] = bool(b.get("allowed"))
            if b.get("always"):
                tool_name = b.get("tool") or ""
                cfg = store.load_config()
                if tool_name and tool_name not in cfg.setdefault("alwaysAllow", []):
                    cfg["alwaysAllow"].append(tool_name)
                    store.save_config(cfg)
            rec["event"].set()
            return self.send_json({"ok": True})

        # 文件写入
        ws = cfg.get("workspace") or str(Path.home())
        if path == "/api/fs/write":
            return self.send_json({"ok": True, **fsops.write_text(ws, b.get("path", ""), b.get("content", ""))})
        if path == "/api/fs/mkdir":
            return self.send_json({"ok": True, **fsops.mkdir(ws, b.get("path", ""))})
        if path == "/api/fs/delete":
            return self.send_json({"ok": True, **fsops.remove(ws, b.get("path", ""))})
        if path == "/api/fs/rename":
            return self.send_json({"ok": True, **fsops.rename(ws, b.get("src", ""), b.get("dst", ""))})

        # 检查点
        if path == "/api/checkpoint/restore":
            restored = checkpoints.restore(b.get("session", ""), b.get("id", ""), ws)
            return self.send_json({"ok": True, "restored": restored})
        if path == "/api/checkpoint/create":
            return self.send_json({"ok": True, "checkpoint": checkpoints.create(b.get("session", ""), b.get("label", ""))})

        # Git 写操作
        if path.startswith("/api/git/"):
            sub = path[len("/api/git/"):]
            if sub == "init":
                r = gitops.run_git(ws, ["init"])
            elif sub == "stage":
                r = gitops.stage(ws, b.get("paths") or [])
            elif sub == "unstage":
                r = gitops.unstage(ws, b.get("paths") or [])
            elif sub == "discard":
                r = gitops.discard(ws, b.get("paths") or [])
            elif sub == "commit":
                r = gitops.commit(ws, b.get("message", ""), b.get("identity"))
            elif sub == "checkout":
                r = gitops.checkout(ws, b.get("ref", ""), bool(b.get("create")))
            else:
                return self.error("未知 Git 操作", 404)
            return self.send_json({"ok": r["code"] == 0, "code": r["code"], "out": r["out"], "err": r["err"]})

        # 终端
        if path == "/api/terms":
            t = TERMS.create(ws, b.get("title") or "终端")
            if b.get("command"):
                t.input_text(b["command"] + "\n")
            return self.send_json({"ok": True, "terminal": t.info()})
        if path == "/api/term/input":
            t = TERMS.get(b.get("id"))
            if not t:
                return self.error("终端不存在", 404)
            if b.get("data_b64"):
                t.write(base64.b64decode(b["data_b64"]))
            else:
                t.input_text(b.get("data", ""))
            return self.send_json({"ok": True})
        if path == "/api/term/resize":
            t = TERMS.get(b.get("id"))
            if t:
                t.resize(int(b.get("cols") or 120), int(b.get("rows") or 32))
            return self.send_json({"ok": True})
        if path == "/api/term/close":
            TERMS.close(b.get("id"))
            return self.send_json({"ok": True})

        # MCP
        if path == "/api/mcp/reload":
            MCPM.reload(cfg.get("mcpServers") or {})
            return self.send_json({"ok": True, "servers": MCPM.status()})
        if path == "/api/mcp/call":
            try:
                out = MCPM.call(b.get("name", ""), b.get("args") or {})
                return self.send_json({"ok": True, "result": out})
            except Exception as e:
                return self.send_json({"ok": False, "error": str(e)})

        # 备份导入
        if path == "/api/backup/import":
            data = b.get("data") or {}
            if data.get("config"):
                store.save_config(data["config"])
            for s in data.get("sessions") or []:
                if s.get("id"):
                    store.save_session(s)
            return self.send_json({"ok": True})

        if path == "/api/backup/save":
            data = {"app": "AiCodeMac", "version": VERSION, "exportedAt": int(time.time() * 1000),
                    "config": cfg, "sessions": []}
            for it in store.list_sessions():
                try:
                    data["sessions"].append(store.load_session(it["id"]))
                except Exception:
                    pass
            out_dir = Path.home() / "Downloads"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            out = out_dir / ("aicode-backup-%s.json" % stamp)
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            return self.send_json({"ok": True, "path": str(out)})

        return self.error("Not Found", 404)

    # ---------------------------------------------------------------- chat
    def chat(self, b, cfg):
        sid = b.get("sessionId") or ""
        try:
            session = store.load_session(sid)
        except FileNotFoundError:
            return self.error("会话不存在", 404)
        text = b.get("text") or ""
        images = b.get("images") or []
        if not text.strip() and not images:
            return self.error("消息为空")
        if b.get("mode"):
            cfg["mode"] = b["mode"]
            store.save_config(cfg)
        if session.get("workspace"):
            cfg["workspace"] = session["workspace"]
        if images:
            parts = []
            if text.strip():
                parts.append({"type": "text", "text": text})
            for img in images[:6]:
                parts.append({"type": "image", "media_type": img.get("media_type", "image/png"),
                              "data": img.get("data", "")})
            content = parts
        else:
            content = text
        session["messages"].append({"role": "user", "content": content})
        store.save_session(session)

        cancel = threading.Event()
        CANCEL[sid] = cancel
        self.sse_start()

        def emit(ev):
            return self.send_sse_safe(ev)

        try:
            run = agent.AgentRun(session, cfg, emit, make_approver(emit), TERMS, MCPM, cancel)
            run.run(text)
        except providers.ProviderError as e:
            emit({"type": "error", "text": str(e)})
        except Exception as e:
            traceback.print_exc()
            emit({"type": "error", "text": "运行失败: %s" % e})
        finally:
            emit({"type": "end"})
            CANCEL.pop(sid, None)
        return None

    def send_sse_safe(self, ev):
        try:
            self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    # ---------------------------------------------------------------- terminal SSE
    def term_stream(self, tid, offset):
        t = TERMS.get(tid)
        if not t:
            return self.error("终端不存在", 404)
        self.sse_start()
        try:
            self.wfile.write(b"retry: 1000\n\n")
            while True:
                data, offset = t.read_from(offset, timeout=15)
                if data:
                    payload = {"type": "data", "data": base64.b64encode(data).decode("ascii"),
                               "offset": offset}
                    if not self.sse_send(payload):
                        break
                elif t.closed:
                    self.sse_send({"type": "exit", "offset": offset})
                    break
                else:
                    if not self.sse_send({"type": "ping", "offset": offset}):
                        break
        except (BrokenPipeError, ConnectionResetError):
            pass
        return None


def pick_folder():
    script = 'POSIX path of (choose folder with prompt "选择工作区目录" default location POSIX file "%s")' % (
        Path.home())
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=120)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    return ""


def find_free_port(preferred=0):
    s = socket.socket()
    s.bind(("127.0.0.1", preferred))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--workspace", default="")
    args = ap.parse_args()

    if args.workspace:
        cfg = store.load_config()
        cfg["workspace"] = str(Path(args.workspace).expanduser().resolve())
        store.save_config(cfg)

    cfg = store.load_config()
    MCPM.reload(cfg.get("mcpServers") or {})
    port = find_free_port(args.port)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    print("AICODE_PORT=%d" % port, flush=True)
    print("AICODE_URL=http://127.0.0.1:%d" % port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
