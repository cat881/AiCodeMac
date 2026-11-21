"""MCP 客户端（stdio 与 HTTP 两种传输，尽力而为）。"""
import json
import os
import queue
import shlex
import subprocess
import threading
import urllib.request


class McpError(Exception):
    pass


class McpClient:
    def __init__(self, name: str, conf: dict):
        self.name = name
        self.conf = conf
        self.proc = None
        self.tools = []
        self.error = ""
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._reader = None
        self._connected = False

    # ---------------- stdio
    def _start_stdio(self):
        cmd = self.conf.get("command", "")
        if not cmd:
            raise McpError("缺少 command")
        argv = shlex.split(cmd) + list(self.conf.get("args") or [])
        env = dict(os.environ)
        env.update(self.conf.get("env") or {})
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=env, bufsize=0)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        while self.proc and self.proc.poll() is None:
            try:
                line = self.proc.stdout.readline()
            except (OSError, ValueError):
                break
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            mid = msg.get("id")
            if mid is not None and mid in self._pending:
                self._pending[mid].put(msg)
        for q in list(self._pending.values()):
            q.put({"error": {"message": "MCP 连接已关闭"}})

    def _stdio_request(self, method, params=None, timeout=30):
        if not self.proc:
            self._start_stdio()
        with self._lock:
            self._id += 1
            mid = self._id
        payload = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            payload["params"] = params
        q = queue.Queue()
        self._pending[mid] = q
        try:
            self.proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError as e:
            raise McpError("写入 MCP 失败: %s" % e)
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty:
            raise McpError("MCP 请求超时: %s" % method)
        finally:
            self._pending.pop(mid, None)
        if "error" in msg:
            raise McpError(msg["error"].get("message", "MCP 错误"))
        return msg.get("result", {})

    # ---------------- http
    def _http_request(self, method, params=None, timeout=40):
        url = self.conf.get("url") or self.conf.get("baseUrl")
        if not url:
            raise McpError("缺少 url")
        payload = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            payload["params"] = params
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        headers.update(self.conf.get("headers") or {})
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception as e:
            raise McpError("HTTP MCP 请求失败: %s" % e)
        if raw.lstrip().startswith("event:") or "\ndata:" in raw:
            data = ""
            for line in raw.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
            raw = data
        try:
            msg = json.loads(raw)
        except Exception:
            raise McpError("MCP 返回无法解析")
        if "error" in msg:
            raise McpError(msg["error"].get("message", "MCP 错误"))
        return msg.get("result", {})

    def request(self, method, params=None, timeout=30):
        if self.conf.get("url") or self.conf.get("baseUrl"):
            return self._http_request(method, params, timeout)
        return self._stdio_request(method, params, timeout)

    def connect(self):
        if self._connected:
            return
        self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "AiCodeMac", "version": "1.0.0"},
        })
        if not (self.conf.get("url") or self.conf.get("baseUrl")):
            try:
                note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                self.proc.stdin.write((json.dumps(note) + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except OSError:
                pass
        self._refresh_tools()
        self._connected = True

    def _refresh_tools(self):
        res = self.request("tools/list", {})
        self.tools = res.get("tools", []) or []

    def call(self, tool: str, args: dict):
        self.connect()
        res = self.request("tools/call", {"name": tool, "arguments": args}, timeout=180)
        content = res.get("content") or []
        texts = []
        for c in content:
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
            else:
                texts.append(json.dumps(c, ensure_ascii=False)[:4000])
        return "\n".join(texts) or json.dumps(res, ensure_ascii=False)[:4000]

    def close(self):
        if self.proc:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None
        self._connected = False


class McpManager:
    def __init__(self):
        self.clients = {}
        self.lock = threading.Lock()

    def reload(self, servers: dict):
        with self.lock:
            for c in self.clients.values():
                c.close()
            self.clients = {}
            for name, conf in (servers or {}).items():
                if not conf.get("enabled", True):
                    continue
                cl = McpClient(name, conf)
                try:
                    cl.connect()
                except Exception as e:
                    cl.error = str(e)
                self.clients[name] = cl

    def tool_specs(self):
        specs = []
        for name, c in self.clients.items():
            for t in c.tools:
                specs.append({
                    "name": "mcp__%s__%s" % (name, t.get("name")),
                    "description": "[MCP:%s] %s" % (name, t.get("description", "")),
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                    "_mcp": (name, t.get("name")),
                })
        return specs

    def call(self, full_name: str, args: dict):
        if not full_name.startswith("mcp__"):
            raise McpError("不是 MCP 工具")
        _, server, tool = full_name.split("__", 2)
        c = self.clients.get(server)
        if not c:
            raise McpError("MCP 服务器未连接: %s" % server)
        return c.call(tool, args)

    def status(self):
        return [{"name": n, "connected": c._connected, "error": c.error,
                 "tools": [t.get("name") for t in c.tools]} for n, c in self.clients.items()]
