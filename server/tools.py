"""Agent 工具定义与执行。"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import checkpoints
import fsops

MAX_OUT = 40_000

TOOL_DEFS = [
    {
        "name": "read_file",
        "description": "读取工作区内的文本文件，返回带行号的内容。适合查看代码、配置或文档。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的文件路径"},
            "start_line": {"type": "integer", "description": "起始行（从 1 开始，可选）"},
            "end_line": {"type": "integer", "description": "结束行（可选）"},
        }, "required": ["path"]},
    },
    {
        "name": "write_file",
        "description": "创建或覆盖写入文件。修改前会自动生成检查点快照，可由用户回滚。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "相对工作区根目录的文件路径"},
            "content": {"type": "string", "description": "完整文件内容"},
        }, "required": ["path", "content"]},
    },
    {
        "name": "edit_file",
        "description": "对文件做精确字符串替换。old_string 必须与文件内容完全一致（含缩进），否则失败。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "要被替换的原文"},
            "new_string": {"type": "string", "description": "替换后的内容"},
            "replace_all": {"type": "boolean", "description": "是否替换所有匹配，默认 false"},
        }, "required": ["path", "old_string", "new_string"]},
    },
    {
        "name": "list_dir",
        "description": "列出目录内容（自动忽略 .git、node_modules 等）。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "目录路径，默认工作区根目录"},
        }},
    },
    {
        "name": "grep_search",
        "description": "在工作区源码中按正则搜索文本，返回 文件:行号:内容。",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "glob": {"type": "string", "description": "文件名过滤，如 *.py"},
            "case_sensitive": {"type": "boolean"},
        }, "required": ["pattern"]},
    },
    {
        "name": "file_search",
        "description": "按文件名通配符查找文件，如 *.kt 或 *config*.json。",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
        }, "required": ["pattern"]},
    },
    {
        "name": "run_shell",
        "description": "在工作区目录执行 Shell 命令（zsh -lc），返回标准输出、标准错误与退出码。适合构建、测试、查看环境。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 120"},
        }, "required": ["command"]},
    },
    {
        "name": "open_terminal",
        "description": "在界面的终端面板中打开一个后台终端并执行命令，适合长时任务（如 dev server）。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令，可为空"},
            "title": {"type": "string"},
        }},
    },
    {
        "name": "todo_write",
        "description": "维护当前任务的待办清单，供用户实时查看进度。每次传入完整列表。",
        "parameters": {"type": "object", "properties": {
            "todos": {"type": "array", "items": {"type": "object", "properties": {
                "content": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
            }, "required": ["content", "status"]}},
        }, "required": ["todos"]},
    },
    {
        "name": "web_fetch",
        "description": "抓取网页并转为纯文本，用于阅读在线文档或接口说明。",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
        }, "required": ["url"]},
    },
    {
        "name": "web_search",
        "description": "使用搜索引擎检索资料，返回标题、链接与摘要。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
        }, "required": ["query"]},
    },
]

WRITE_TOOLS = {"write_file", "edit_file", "open_terminal", "run_shell"}


def _truncate(s: str, n=MAX_OUT):
    if len(s) <= n:
        return s
    return s[:n] + "\n…（输出已截断，共 %d 字符）" % len(s)


def _strip_html(html: str):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|br)>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ToolContext:
    def __init__(self, workspace, session, checkpoint_id, emit, terms, mcpmanager):
        self.workspace = workspace
        self.session = session
        self.checkpoint_id = checkpoint_id
        self.emit = emit
        self.terms = terms
        self.mcp = mcpmanager


def execute(ctx: ToolContext, name: str, args: dict) -> str:
    try:
        if name == "read_file":
            return _read_file(ctx, args)
        if name == "write_file":
            return _write_file(ctx, args)
        if name == "edit_file":
            return _edit_file(ctx, args)
        if name == "list_dir":
            return _list_dir(ctx, args)
        if name == "grep_search":
            return _grep(ctx, args)
        if name == "file_search":
            return _file_search(ctx, args)
        if name == "run_shell":
            return _run_shell(ctx, args)
        if name == "open_terminal":
            return _open_terminal(ctx, args)
        if name == "todo_write":
            return _todo(ctx, args)
        if name == "web_fetch":
            return _web_fetch(ctx, args)
        if name == "web_search":
            return _web_search(ctx, args)
        if name.startswith("mcp__"):
            return ctx.mcp.call(name, args)
        return "未知工具: %s" % name
    except fsops.FsError as e:
        return "错误: %s" % e
    except Exception as e:
        return "工具执行失败: %s" % e


def _read_file(ctx, a):
    rel = a.get("path", "")
    data = fsops.read_text(ctx.workspace, rel)
    lines = data["content"].splitlines()
    start = max(int(a.get("start_line") or 1), 1)
    end = min(int(a.get("end_line") or len(lines)), len(lines))
    body = "\n".join("%5d→%s" % (i, lines[i - 1]) for i in range(start, end + 1))
    head = "文件: %s（共 %d 行%s）\n" % (data["path"], len(lines), "，已截断" if data["truncated"] else "")
    return _truncate(head + body)


def _write_file(ctx, a):
    rel = a.get("path", "")
    content = a.get("content", "")
    checkpoints.snapshot(ctx.session["id"], ctx.checkpoint_id, ctx.workspace, rel)
    fsops.write_text(ctx.workspace, rel, content)
    return "已写入 %s（%d 字符）" % (rel, len(content))


def _edit_file(ctx, a):
    rel = a.get("path", "")
    old = a.get("old_string", "")
    new = a.get("new_string", "")
    data = fsops.read_text(ctx.workspace, rel)
    text = data["content"]
    count = text.count(old)
    if old == "":
        return "错误: old_string 不能为空"
    if count == 0:
        return "错误: 未找到要替换的内容，请先用 read_file 确认原文（注意缩进与空白）。"
    if count > 1 and not a.get("replace_all"):
        return "错误: 找到 %d 处匹配，请提供更长的唯一上下文，或设置 replace_all=true。" % count
    checkpoints.snapshot(ctx.session["id"], ctx.checkpoint_id, ctx.workspace, rel)
    n = text.count(old) if a.get("replace_all") else 1
    text = text.replace(old, new) if a.get("replace_all") else text.replace(old, new, 1)
    fsops.write_text(ctx.workspace, rel, text)
    return "已修改 %s（替换 %d 处）" % (rel, n)


def _list_dir(ctx, a):
    rel = a.get("path") or "."
    t = fsops.tree(ctx.workspace, rel, depth=2)
    def fmt(node, depth=0):
        line = "  " * depth + ("📁 " if node.get("dir") else "📄 ") + node["name"]
        rows = [line]
        for c in node.get("children", [])[:200]:
            rows.append(fmt(c, depth + 1))
        return "\n".join(rows)
    return _truncate(fmt(t))


def _grep(ctx, a):
    rows = fsops.search(ctx.workspace, a.get("pattern", ""), a.get("glob", ""),
                        case_sensitive=bool(a.get("case_sensitive")))
    if not rows:
        return "没有匹配结果"
    return _truncate("\n".join("%s:%d: %s" % (r["path"], r["line"], r["text"]) for r in rows))


def _file_search(ctx, a):
    rows = fsops.find_files(ctx.workspace, a.get("pattern", "*"))
    return _truncate("\n".join(rows) or "没有找到文件")


def _run_shell(ctx, a):
    cmd = a.get("command", "")
    timeout = min(int(a.get("timeout") or 120), 900)
    env = dict(os.environ)
    env["PAGER"] = "cat"
    p = subprocess.run(["/bin/zsh", "-lc", cmd], cwd=ctx.workspace, capture_output=True,
                       timeout=timeout, env=env)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    res = "退出码: %d\n" % p.returncode
    if out:
        res += "--- stdout ---\n" + out
    if err:
        res += "\n--- stderr ---\n" + err
    if not out and not err:
        res += "（无输出）"
    return _truncate(res)


def _open_terminal(ctx, a):
    t = ctx.terms.create(ctx.workspace, a.get("title") or "Agent 终端")
    if a.get("command"):
        t.input_text(a["command"] + "\n")
    ctx.emit({"type": "terminal_open", "id": t.id, "title": t.title})
    return "已在界面终端面板创建会话（id=%s）" % t.id


def _todo(ctx, a):
    todos = a.get("todos") or []
    clean = []
    for t in todos:
        c = str(t.get("content", "")).strip()
        if not c:
            continue
        st = t.get("status", "pending")
        if st not in ("pending", "in_progress", "completed"):
            st = "pending"
        clean.append({"content": c, "status": st})
    ctx.session["todos"] = clean
    ctx.emit({"type": "todos", "todos": clean})
    return "待办已更新（%d 项）" % len(clean)


def _web_fetch(ctx, a):
    url = a.get("url", "")
    if not re.match(r"^https?://", url):
        return "错误: 只支持 http/https URL"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read(3_000_000)
        charset = r.headers.get_content_charset() or "utf-8"
    html = raw.decode(charset, "replace")
    text = _strip_html(html)
    return _truncate("URL: %s\n\n%s" % (url, text), 30000)


def _web_search(ctx, a):
    q = a.get("query", "")
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    items = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        html, re.S)
    if not items:
        return "搜索无结果（可能被限流），可改用 web_fetch 直接访问已知网址。"
    rows = []
    for i, (href, title, snippet) in enumerate(items[:8], 1):
        title = _strip_html(title)
        snippet = _strip_html(snippet)
        href = urllib.parse.unquote(href)
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            href = urllib.parse.unquote(m.group(1))
        rows.append("%d. %s\n   %s\n   %s" % (i, title, href, snippet))
    return _truncate("\n\n".join(rows), 12000)
