"""AI 供应商适配：OpenAI / Anthropic / Gemini 协议，统一流式接口。"""
import json
import threading
import urllib.error
import urllib.request

_rot_state = {}
_rot_lock = threading.Lock()


class ProviderError(Exception):
    pass


def pick_key(provider: dict, rotation: str = "sequential") -> str:
    keys = [k.strip() for k in provider.get("keys", []) if k and k.strip()]
    if not keys:
        raise ProviderError("供应商 %s 未配置 API Key" % provider.get("name"))
    pid = provider.get("id")
    with _rot_lock:
        idx = _rot_state.get(pid, 0) % len(keys)
        if rotation == "round_robin":
            _rot_state[pid] = idx + 1
        return keys[idx]


def _opener(proxy: str = ""):
    handlers = []
    if proxy.strip():
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _post_stream(url, headers, payload, proxy=""):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = _opener(proxy)
    try:
        return opener.open(req, timeout=600)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise ProviderError("HTTP %s: %s" % (e.code, body[:2000]))
    except urllib.error.URLError as e:
        raise ProviderError("网络错误: %s" % e.reason)


def _iter_sse(resp):
    """逐行解析 SSE，返回 (event, data)。"""
    event = ""
    buf = b""
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.rstrip(b"\r").decode("utf-8", "replace")
            if not line:
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                yield event, line[5:].strip()


# ---------------------------------------------------------------- OpenAI
def _openai_messages(messages):
    out = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id"), "content": m.get("content", "")})
            continue
        if role == "assistant":
            msg = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc.get("arguments") or "{}"}}
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            parts = []
            for p in content:
                if p.get("type") == "text":
                    parts.append({"type": "text", "text": p.get("text", "")})
                elif p.get("type") == "image":
                    parts.append({"type": "image_url", "image_url": {
                        "url": "data:%s;base64,%s" % (p.get("media_type", "image/png"), p.get("data", ""))}})
            out.append({"role": "user", "content": parts})
        else:
            out.append({"role": "user", "content": content})
    return out


def stream_openai(provider, model, messages, tools, system, on_text, on_reasoning, proxy=""):
    base = (provider.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
    key = pick_key(provider)
    msgs = ([{"role": "system", "content": system}] if system else []) + _openai_messages(messages)
    payload = {"model": model, "messages": msgs, "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    resp = _post_stream(base + "/chat/completions", headers, payload, proxy)
    text, reasoning = [], []
    calls = {}
    usage = {"input": 0, "output": 0}
    with resp:
        for _, data in _iter_sse(resp):
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue
            if obj.get("usage"):
                usage = {"input": obj["usage"].get("prompt_tokens", 0),
                         "output": obj["usage"].get("completion_tokens", 0)}
            for ch in obj.get("choices", []):
                d = ch.get("delta") or {}
                if d.get("reasoning_content"):
                    reasoning.append(d["reasoning_content"])
                    on_reasoning(d["reasoning_content"])
                if d.get("content"):
                    text.append(d["content"])
                    on_text(d["content"])
                for tc in d.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
    tool_calls = []
    for idx in sorted(calls):
        c = calls[idx]
        if c["name"]:
            tool_calls.append({"id": c["id"] or ("call_%s" % idx), "name": c["name"],
                               "arguments": c["arguments"] or "{}"})
    return {"content": "".join(text), "reasoning": "".join(reasoning), "tool_calls": tool_calls, "usage": usage}


# ---------------------------------------------------------------- Anthropic
def _anthropic_messages(messages):
    out = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id"), "content": m.get("content", "")}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                try:
                    inp = json.loads(tc.get("arguments") or "{}")
                except Exception:
                    inp = {}
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": blocks})
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            blocks = []
            for p in content:
                if p.get("type") == "text":
                    blocks.append({"type": "text", "text": p.get("text", "")})
                elif p.get("type") == "image":
                    blocks.append({"type": "image", "source": {
                        "type": "base64", "media_type": p.get("media_type", "image/png"), "data": p.get("data", "")}})
            out.append({"role": "user", "content": blocks})
        else:
            out.append({"role": "user", "content": [{"type": "text", "text": content}]})
    return out


def stream_anthropic(provider, model, messages, tools, system, on_text, on_reasoning, proxy=""):
    base = (provider.get("baseUrl") or "https://api.anthropic.com").rstrip("/")
    if not base.endswith("/v1"):
        url = base + "/v1/messages"
    else:
        url = base + "/messages"
    key = pick_key(provider)
    payload = {"model": model, "max_tokens": 8192, "stream": True,
               "messages": _anthropic_messages(messages)}
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [{"name": t["name"], "description": t.get("description", ""),
                             "input_schema": t.get("parameters", {"type": "object", "properties": {}})}
                            for t in tools]
    headers = {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    resp = _post_stream(url, headers, payload, proxy)
    text, reasoning, calls = [], [], {}
    usage = {"input": 0, "output": 0}
    with resp:
        for event, data in _iter_sse(resp):
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue
            t = obj.get("type") or event
            if t == "message_start":
                usage["input"] = (obj.get("message", {}).get("usage", {}) or {}).get("input_tokens", 0)
            elif t == "content_block_start":
                blk = obj.get("content_block", {})
                if blk.get("type") == "tool_use":
                    calls[obj.get("index", 0)] = {"id": blk.get("id"), "name": blk.get("name"), "arguments": ""}
            elif t == "content_block_delta":
                d = obj.get("delta", {})
                if d.get("type") == "text_delta":
                    text.append(d.get("text", ""))
                    on_text(d.get("text", ""))
                elif d.get("type") in ("thinking_delta", "reasoning_delta"):
                    reasoning.append(d.get("thinking", ""))
                    on_reasoning(d.get("thinking", ""))
                elif d.get("type") == "input_json_delta":
                    slot = calls.setdefault(obj.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    slot["arguments"] += d.get("partial_json", "")
            elif t == "message_delta":
                usage["output"] = (obj.get("usage", {}) or {}).get("output_tokens", usage["output"])
    tool_calls = [{"id": c["id"] or ("call_%d" % i), "name": c["name"], "arguments": c["arguments"] or "{}"}
                  for i, c in sorted(calls.items()) if c["name"]]
    return {"content": "".join(text), "reasoning": "".join(reasoning), "tool_calls": tool_calls, "usage": usage}


# ---------------------------------------------------------------- Gemini
def _gemini_contents(messages):
    out = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            name = m.get("name") or "tool"
            out.append({"role": "user", "parts": [{"functionResponse": {"name": name, "response": {
                "content": m.get("content", "")}}}]})
            continue
        if role == "assistant":
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                try:
                    args = json.loads(tc.get("arguments") or "{}")
                except Exception:
                    args = {}
                parts.append({"functionCall": {"name": tc["name"], "args": args}})
            if not parts:
                parts = [{"text": ""}]
            out.append({"role": "model", "parts": parts})
            continue
        content = m.get("content", "")
        if isinstance(content, list):
            parts = []
            for p in content:
                if p.get("type") == "text":
                    parts.append({"text": p.get("text", "")})
                elif p.get("type") == "image":
                    parts.append({"inlineData": {"mimeType": p.get("media_type", "image/png"),
                                                 "data": p.get("data", "")}})
            out.append({"role": "user", "parts": parts})
        else:
            out.append({"role": "user", "parts": [{"text": content}]})
    return out


def stream_gemini(provider, model, messages, tools, system, on_text, on_reasoning, proxy=""):
    base = (provider.get("baseUrl") or "https://generativelanguage.googleapis.com").rstrip("/")
    key = pick_key(provider)
    url = "%s/v1beta/models/%s:streamGenerateContent?alt=sse&key=%s" % (base, model, urllib.parse.quote(key))
    payload = {"contents": _gemini_contents(messages)}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        decls = []
        for t in tools:
            decls.append({"name": t["name"], "description": t.get("description", ""),
                          "parameters": t.get("parameters", {"type": "object", "properties": {}})})
        payload["tools"] = [{"functionDeclarations": decls}]
    headers = {"Content-Type": "application/json"}
    resp = _post_stream(url, headers, payload, proxy)
    text, reasoning, calls = [], [], []
    usage = {"input": 0, "output": 0}
    with resp:
        for _, data in _iter_sse(resp):
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue
            um = obj.get("usageMetadata") or {}
            if um:
                usage = {"input": um.get("promptTokenCount", usage["input"]),
                         "output": um.get("candidatesTokenCount", usage["output"])}
            for cand in obj.get("candidates", []):
                for part in (cand.get("content") or {}).get("parts", []):
                    if part.get("text"):
                        text.append(part["text"])
                        on_text(part["text"])
                    if part.get("thought") and part.get("text"):
                        reasoning.append(part["text"])
                    fc = part.get("functionCall")
                    if fc:
                        calls.append({"id": "call_%d" % len(calls), "name": fc.get("name"),
                                      "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False)})
    return {"content": "".join(text), "reasoning": "".join(reasoning), "tool_calls": calls, "usage": usage}


import urllib.parse  # noqa: E402  (gemini URL 编码)


def stream(provider, model, messages, tools, system, on_text, on_reasoning, proxy=""):
    proto = provider.get("protocol", "openai")
    if proto == "anthropic":
        return stream_anthropic(provider, model, messages, tools, system, on_text, on_reasoning, proxy)
    if proto == "gemini":
        return stream_gemini(provider, model, messages, tools, system, on_text, on_reasoning, proxy)
    return stream_openai(provider, model, messages, tools, system, on_text, on_reasoning, proxy)


def simple_complete(provider, model, system, prompt, proxy=""):
    """非流式摘要请求。"""
    res = stream(provider, model, [{"role": "user", "content": prompt}], [], system,
                 lambda _t: None, lambda _t: None, proxy)
    return res.get("content", "")
