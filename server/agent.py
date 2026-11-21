"""Agent 主循环：流式对话、工具调用、模式管控、检查点与上下文压缩。"""
import datetime
import json
import os
import re
import threading
import time
from pathlib import Path

import checkpoints
import providers
import store
import tools

SYSTEM_TEMPLATE = """你是 AiCode，运行在 macOS 桌面端的 AI 编程 Agent。你像一名资深工程师一样工作：先理解代码，再动手修改，并在修改后验证。

当前工作区：{workspace}
系统：macOS（arm64），当前时间：{now}
运行模式：{mode} — {mode_desc}
界面语言：{language}

工作准则：
1. 先用 list_dir / read_file / grep_search 了解现状，不要凭空猜测文件内容或路径。
2. 修改代码优先使用 edit_file 做精确替换；只有新文件或整文件重写时才用 write_file。
3. 工具返回的路径都是相对工作区的；回复中用 `文件路径:行号` 的形式引用代码，界面会渲染为可点击链接。
4. 执行构建/测试用 run_shell；长时任务（dev server、watch）用 open_terminal。
5. 多步骤任务用 todo_write 维护清单并及时更新状态。
6. 回复保持简洁，用中文说明你做了什么、结果如何、下一步建议；不要输出无意义的客套话。
7. 不要伪造命令输出或测试结果。失败时如实说明并分析原因。
{mode_rules}
{memory}
{skills}
{user_prompt}"""

MODE_DESC = {
    "build": "正常开发，写操作需要用户授权",
    "plan": "只读规划，禁止修改文件或执行写操作",
    "auto": "全自动，所有工具调用免授权",
}


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def est_tokens(messages):
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        n += len(str(c or "")) + sum(len(str(t)) for t in m.get("tool_calls") or [])
    return int(n / 3)


class AgentRun:
    def __init__(self, session, cfg, emit, request_approval, terms, mcp, cancel_event):
        self.session = session
        self.cfg = cfg
        self.emit = emit
        self.request_approval = request_approval
        self.terms = terms
        self.mcp = mcp
        self.cancel = cancel_event
        self.workspace = session.get("workspace") or cfg.get("workspace") or str(Path.home())
        self.mode = cfg.get("mode", "build")
        self.provider = None
        self.model = ""
        self.checkpoint_id = ""
        self.turn_files = []
        self.pending_text = []

    # ---------------------------------------------------------------- provider
    def _resolve_provider(self):
        active = self.cfg.get("active", {})
        pid = active.get("providerId")
        provs = self.cfg.get("providers", [])
        prov = next((p for p in provs if p.get("id") == pid), None)
        if not prov and provs:
            prov = provs[0]
        if not prov:
            raise providers.ProviderError("尚未配置 AI 供应商，请到「设置 → AI 供应商」添加并填写 API Key。")
        model = active.get("model")
        if not model:
            ms = prov.get("models") or []
            if not ms:
                raise providers.ProviderError("供应商 %s 没有可用模型" % prov.get("name"))
            model = ms[0]["id"]
        return prov, model

    def _price(self):
        for m in self.provider.get("models", []):
            if m.get("id") == self.model:
                return float(m.get("input") or 0), float(m.get("output") or 0)
        return 0.0, 0.0

    # ---------------------------------------------------------------- prompt
    def _build_system(self):
        lang = "中文" if self.cfg.get("language") == "zh" else "English"
        if self.mode == "plan":
            rules = "\nPLAN 模式：你只能读取和分析，不能写文件、改文件或执行会修改系统的命令；输出实施计划。"
        elif self.mode == "auto":
            rules = "\nAUTO 模式：用户已授权你直接执行所有工具操作，请谨慎并优先创建检查点。"
        else:
            rules = ""
        memory = ""
        for fn in ("AGENTS.md", "AICODE.md", "CLAUDE.md"):
            p = Path(self.workspace) / fn
            if p.exists():
                try:
                    memory += "\n\n## 项目记忆（%s）\n%s" % (fn, p.read_text("utf-8", "replace")[:4000])
                except OSError:
                    pass
        skills = ""
        dirs = [Path(self.workspace) / ".aicode" / "skills", store.DATA / "skills"]
        found = []
        for d in dirs:
            if d.is_dir():
                for sd in sorted(d.iterdir()):
                    f = sd / "SKILL.md" if sd.is_dir() else None
                    if f and f.exists():
                        try:
                            found.append("\n### 技能：%s\n%s" % (sd.name, f.read_text("utf-8", "replace")[:2500]))
                        except OSError:
                            pass
        if found:
            skills = "\n\n## 可用技能（按需参考）\n" + "\n".join(found[:6])
        user_prompt = ""
        if (self.cfg.get("systemPrompt") or "").strip():
            user_prompt = "\n\n## 用户的额外指令\n" + self.cfg["systemPrompt"].strip()
        return SYSTEM_TEMPLATE.format(
            workspace=self.workspace, now=now_str(), mode=self.mode.upper(),
            mode_desc=MODE_DESC.get(self.mode, ""), language=lang,
            mode_rules=rules, memory=memory, skills=skills, user_prompt=user_prompt,
        )

    # ---------------------------------------------------------------- approval
    def _allow(self, tool_name, summary, detail=""):
        if self.mode == "auto":
            return True
        if self.mode == "plan" and (tool_name in tools.WRITE_TOOLS or tool_name.startswith("mcp__")):
            self.emit({"type": "notice", "text": "PLAN 模式下已拦截写操作：%s" % tool_name})
            return False
        if tool_name in (self.cfg.get("alwaysAllow") or []):
            return True
        perm = self.cfg.get("permissions", {}).get(
            "mcp_call" if tool_name.startswith("mcp__") else tool_name, "ask")
        if perm == "allow":
            return True
        if perm == "deny":
            self.emit({"type": "notice", "text": "工具 %s 已被设置为禁止" % tool_name})
            return False
        return self.request_approval(tool_name, summary, detail)

    # ---------------------------------------------------------------- main
    def run(self, user_content):
        self.provider, self.model = self._resolve_provider()
        if not str(user_content).strip() and not self.session["messages"]:
            return
        cp = checkpoints.create(self.session["id"], str(user_content)[:40])
        self.checkpoint_id = cp["id"]
        self.session.setdefault("checkpoints", []).insert(0, {"id": cp["id"], "ts": cp["ts"],
                                                              "label": cp["label"]})
        self.session["checkpoints"] = self.session["checkpoints"][:40]
        store.save_session(self.session)

        self.emit({"type": "start", "sessionId": self.session["id"], "checkpointId": cp["id"],
                   "provider": self.provider.get("name"), "model": self.model, "mode": self.mode})

        max_steps = 24
        for step in range(max_steps):
            if self.cancel.is_set():
                self.emit({"type": "notice", "text": "已停止生成"})
                break
            self._maybe_compress()
            system = self._build_system()
            specs = [dict(t) for t in tools.TOOL_DEFS]
            for s in self.mcp.tool_specs():
                specs.append({k: v for k, v in s.items() if not k.startswith("_")})

            buf = {"text": [], "reasoning": []}

            def on_text(t):
                if self.cancel.is_set():
                    return
                buf["text"].append(t)
                self.emit({"type": "text", "text": t})

            def on_reason(t):
                if self.cancel.is_set():
                    return
                buf["reasoning"].append(t)
                self.emit({"type": "reasoning", "text": t})

            try:
                res = providers.stream(
                    self.provider, self.model, self.session["messages"], specs, system,
                    on_text, on_reason, proxy=self.cfg.get("proxy", ""))
            except providers.ProviderError as e:
                self.emit({"type": "error", "text": str(e)})
                break

            assistant = {"role": "assistant", "content": res.get("content", ""),
                         "tool_calls": res.get("tool_calls") or []}
            if res.get("reasoning"):
                assistant["reasoning"] = res["reasoning"]
            self.session["messages"].append(assistant)
            self._record_usage(res.get("usage") or {})
            store.save_session(self.session)

            if not assistant["tool_calls"]:
                break

            for tc in assistant["tool_calls"]:
                if self.cancel.is_set():
                    break
                name = tc.get("name", "")
                try:
                    args = json.loads(tc.get("arguments") or "{}")
                except Exception:
                    args = {}
                self.emit({"type": "tool_call", "id": tc["id"], "name": name, "args": args})
                summary, detail = self._preview(name, args)
                allowed = True
                if name in tools.WRITE_TOOLS or name.startswith("mcp__"):
                    allowed = self._allow(name, summary, detail)
                if allowed:
                    try:
                        out = tools.execute(tools.ToolContext(
                            self.workspace, self.session, self.checkpoint_id, self.emit,
                            self.terms, self.mcp), name, args)
                    except Exception as e:
                        out = "工具执行失败: %s" % e
                else:
                    out = "用户拒绝了此操作。" if name in tools.WRITE_TOOLS else "操作被模式或权限策略拦截。"
                err = out.startswith("错误") or out.startswith("工具执行失败")
                self.session["messages"].append({
                    "role": "tool", "tool_call_id": tc["id"], "name": name, "content": out})
                self.emit({"type": "tool_result", "id": tc["id"], "name": name,
                           "content": out[:20000], "error": err})
                store.save_session(self.session)

        if self.session.get("title") in ("", "新会话", None):
            first = next((m for m in self.session["messages"] if m["role"] == "user"), None)
            if first:
                text = first.get("content")
                if isinstance(text, list):
                    text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
                text = re.sub(r"\s+", " ", str(text)).strip()
                if text:
                    self.session["title"] = text[:24]
                    self.emit({"type": "title", "title": self.session["title"]})
        store.save_session(self.session)
        self.emit({"type": "done", "sessionId": self.session["id"], "checkpointId": self.checkpoint_id})

    def _preview(self, name, args):
        if name == "run_shell":
            cmd = args.get("command", "")
            return "执行 Shell 命令", cmd
        if name == "write_file":
            return "写入文件 %s" % args.get("path", ""), (args.get("content") or "")[:1200]
        if name == "edit_file":
            return "修改文件 %s" % args.get("path", ""), \
                "- " + str(args.get("old_string", ""))[:500] + "\n+ " + str(args.get("new_string", ""))[:500]
        if name == "open_terminal":
            return "打开终端", args.get("command", "")
        if name.startswith("mcp__"):
            return "调用 MCP 工具 %s" % name, json.dumps(args, ensure_ascii=False)[:800]
        return "调用工具 %s" % name, json.dumps(args, ensure_ascii=False)[:800]

    def _record_usage(self, usage):
        pin, pout = self._price()
        i, o = int(usage.get("input") or 0), int(usage.get("output") or 0)
        cost = i / 1e6 * pin + o / 1e6 * pout
        rec = {"providerId": self.provider.get("id"), "provider": self.provider.get("name"),
               "model": self.model, "input": i, "output": o, "cost": round(cost, 6),
               "sessionId": self.session["id"]}
        store.record_stats(rec)
        self.emit({"type": "usage", "usage": rec})

    def _maybe_compress(self):
        limit = int(self.cfg.get("contextLimit") or 128000)
        ratio = float(self.cfg.get("compressRatio") or 0.6)
        msgs = self.session["messages"]
        if est_tokens(msgs) < limit * ratio or len(msgs) < 10:
            return
        self.emit({"type": "notice", "text": "上下文接近上限，正在压缩历史对话…"})
        keep = msgs[-6:]
        old = msgs[:-6]
        text = []
        for m in old:
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            text.append("%s: %s" % (m.get("role"), str(c or "")[:1500]))
            for tc in m.get("tool_calls") or []:
                text.append("tool_call %s(%s)" % (tc.get("name"), str(tc.get("arguments"))[:300]))
        try:
            summary = providers.simple_complete(
                self.provider, self.model,
                "你负责压缩对话历史。保留目标、已完成操作、关键文件路径、未决问题。用中文输出要点。",
                "\n".join(text)[:60000], proxy=self.cfg.get("proxy", ""))
        except Exception:
            return
        note = {"role": "user", "content": "【此前对话摘要】\n" + summary}
        self.session["messages"] = [note] + keep
        store.save_session(self.session)
        self.emit({"type": "notice", "text": "历史对话已压缩。"})
