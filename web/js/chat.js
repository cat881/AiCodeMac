/* 会话、流式聊天、工具卡片、审批与检查点 */
(function () {
  const A = window.A;

  // ---------------------------------------------------------------- 会话列表
  A.renderSessions = function () {
    const host = A.$("#session-list");
    if (!host) return;
    const q = (A.state.sessionQuery || "").toLowerCase();
    host.innerHTML = "";
    const items = A.state.sessions.filter((s) => !q || (s.title || "").toLowerCase().includes(q));
    if (!items.length) {
      host.innerHTML = `<div class="muted" style="padding:14px 10px;font-size:12px">${A.t("noSession")}</div>`;
      return;
    }
    items.forEach((s) => {
      const active = A.state.session && A.state.session.id === s.id;
      const el = A.h(`<div class="session-item ${active ? "active" : ""}">
        <div class="st"><div class="t">${A.esc(s.title || A.t("untitled"))}</div>
        <div class="d">${A.fmtTime(s.updatedAt)} · ${s.messageCount} 条</div></div>
        <button class="del" title="删除">${A.icon("trash")}</button></div>`);
      el.onclick = (e) => {
        if (e.target.closest(".del")) return;
        A.loadSession(s.id);
      };
      el.querySelector(".del").onclick = async (e) => {
        e.stopPropagation();
        const ok = await A.confirm("删除会话", `<p>确定删除「${A.esc(s.title || "新会话")}」？此操作不可撤销。</p>`);
        if (!ok) return;
        try {
          await fetch("/api/session/" + s.id, { method: "DELETE" });
          A.state.sessions = A.state.sessions.filter((x) => x.id !== s.id);
          if (A.state.session && A.state.session.id === s.id) {
            A.state.session = null;
            A.renderChat();
          }
          A.renderSessions();
        } catch (err) { A.toast(err.message, "err"); }
      };
      host.appendChild(el);
    });
  };

  A.loadSession = async function (id) {
    try {
      const data = await A.api("/api/session/" + id);
      A.state.session = data.session;
      A.renderSessions();
      A.renderChat();
      A.setView("chat");
      A.$("#view-title").textContent = data.session.title || "会话";
      A.renderTodos();
    } catch (e) { A.toast(e.message, "err"); }
  };

  A.newSession = async function () {
    try {
      const data = await A.api("/api/session/new", { method: "POST", body: {} });
      A.state.session = data.session;
      A.state.sessions.unshift({
        id: data.session.id, title: data.session.title, messageCount: 0,
        createdAt: data.session.createdAt, updatedAt: data.session.updatedAt,
      });
      A.renderSessions();
      A.renderChat();
      A.setView("chat");
      A.$("#input").focus();
    } catch (e) { A.toast(e.message, "err"); }
  };

  // ---------------------------------------------------------------- 欢迎页
  function welcomeHtml() {
    const chips = [
      "介绍一下这个项目的结构",
      "修复所有明显的 bug 并运行测试",
      "帮我实现一个新功能",
      "解释这段代码的工作原理",
    ];
    return `<div class="welcome">
      <h1>${A.t("emptyWelcome")}</h1>
      <p>${A.t("emptySub")}</p>
      <div class="chips">${chips.map((c) => `<button class="chip-sug">${A.esc(c)}</button>`).join("")}</div>
    </div>`;
  }

  // ---------------------------------------------------------------- 渲染消息
  A.renderChat = function () {
    const host = A.$("#messages");
    const session = A.state.session;
    if (!session || !session.messages || !session.messages.length) {
      host.innerHTML = welcomeHtml();
      A.$$(".chip-sug", host).forEach((b) => {
        b.onclick = () => {
          const input = A.$("#input");
          input.value = b.textContent;
          input.focus();
          autoSize(input);
        };
      });
      A.renderTodos();
      return;
    }
    host.innerHTML = "";
    const results = {};
    session.messages.forEach((m) => {
      if (m.role === "tool") results[m.tool_call_id] = m;
    });
    session.messages.forEach((m) => {
      if (m.role === "user") host.appendChild(userMsg(m));
      else if (m.role === "assistant") host.appendChild(assistantMsg(m, results));
    });
    bindToolCards(host);
    scrollBottom(true);
    A.renderTodos();
  };

  function userMsg(m) {
    let text = "";
    const imgs = [];
    if (Array.isArray(m.content)) {
      m.content.forEach((p) => {
        if (p.type === "text") text += p.text || "";
        if (p.type === "image") imgs.push(`data:${p.media_type || "image/png"};base64,${p.data}`);
      });
    } else text = m.content || "";
    const el = A.h(`<div class="msg user"><div class="avatar">你</div><div class="content">
      <div class="bubble">${A.esc(text)}${imgs.map((src) => `<img src="${src}">`).join("")}</div></div></div>`);
    return el;
  }

  function assistantMsg(m, results) {
    const el = A.h(`<div class="msg assistant"><div class="avatar">AI</div><div class="content">
      <div class="meta">AiCode</div></div></div>`);
    const content = el.querySelector(".content");
    if (m.reasoning) {
      const det = A.h(`<details class="reasoning"><summary>${A.t("thinking")}</summary><div class="rtext">${A.esc(m.reasoning)}</div></details>`);
      content.appendChild(det);
    }
    if (m.content) {
      const bubble = A.h(`<div class="bubble md"></div>`);
      bubble.innerHTML = A.renderMarkdown(m.content);
      A.decorateMarkdown(bubble);
      content.appendChild(bubble);
    }
    (m.tool_calls || []).forEach((tc) => {
      let args = {};
      try { args = JSON.parse(tc.arguments || "{}"); } catch (e) {}
      const res = results[tc.id];
      content.appendChild(toolCard(tc.id, tc.name, args, res ? res.content : "", res ? !res.content.startsWith("错误") : false, !!res));
    });
    return el;
  }

  function toolSummary(name, args) {
    if (!args) return "";
    if (name === "run_shell") return args.command || "";
    if (name === "read_file" || name === "write_file" || name === "edit_file") return args.path || "";
    if (name === "grep_search") return args.pattern || "";
    if (name === "todo_write") return "更新待办";
    if (name === "open_terminal") return args.command || args.title || "";
    return Object.keys(args).slice(0, 2).map((k) => k + "=" + String(args[k]).slice(0, 60)).join(" ");
  }

  function toolCard(id, name, args, output, ok, hasResult) {
    const summary = toolSummary(name, args);
    const el = A.h(`<div class="tool-card ${hasResult ? (ok ? "ok" : "err") : "running"}" data-id="${A.esc(id || "")}">
      <div class="tc-head"><span class="dot"></span><span class="tc-name">${A.esc(name)}</span>
      <span class="tc-sum">${A.esc(summary)}</span><span class="tc-chev">▾</span></div>
      <div class="tc-body hidden"><div class="tc-args">${A.esc(JSON.stringify(args || {}, null, 2))}</div>
      <pre class="tc-out">${A.esc(output || "")}</pre></div></div>`);
    el.querySelector(".tc-head").onclick = () => el.querySelector(".tc-body").classList.toggle("hidden");
    el._args = args || {};
    el._name = name;
    return el;
  }

  function bindToolCards(root) {
    root.querySelectorAll(".tool-card").forEach((el) => {
      if (el._bound) return;
      el._bound = true;
    });
  }

  function scrollBottom(force) {
    const host = A.$("#messages");
    if (!host) return;
    const near = host.scrollHeight - host.scrollTop - host.clientHeight < 220;
    if (force || near) host.scrollTop = host.scrollHeight;
  }

  // ---------------------------------------------------------------- 待办与检查点
  A.renderTodos = function () {
    const host = A.$("#todo-strip");
    if (!host) return;
    host.innerHTML = "";
    const todos = (A.state.session && A.state.session.todos) || [];
    todos.forEach((t) => {
      const cls = t.status === "completed" ? "done" : t.status === "in_progress" ? "doing" : "";
      host.appendChild(A.h(`<span class="todo-chip ${cls}"><span class="tdot"></span>${A.esc(t.content)}</span>`));
    });
    const cps = (A.state.session && A.state.session.checkpoints) || [];
    if (cps.length) {
      const btn = A.h(`<button class="ghost-btn" id="btn-rollback" style="font-size:11px;padding:2px 9px">回滚到检查点</button>`);
      btn.onclick = () => rollback(cps[0]);
      host.appendChild(btn);
    }
  };

  async function rollback(cp) {
    const ok = await A.confirm("回滚代码", `<p>将把本次对话中被修改的文件恢复到检查点 <span class="mono">${cp.id}</span> 的状态，确定继续？</p>`);
    if (!ok) return;
    try {
      const r = await A.api("/api/checkpoint/restore", {
        method: "POST", body: { session: A.state.session.id, id: cp.id },
      });
      A.toast("已恢复 " + r.restored.length + " 个文件", "ok");
      A.loadTree();
      if (A.state.activeTab) A.openFile(A.state.activeTab.path);
      if (A.state.view === "git") A.loadGit();
    } catch (e) { A.toast(e.message, "err"); }
  }

  // ---------------------------------------------------------------- 发送
  A.sendMessage = async function () {
    if (A.state.streaming) return;
    const input = A.$("#input");
    const text = input.value.trim();
    if (!text && !A.state.attachments.length) return;
    if (!A.state.session) await A.newSession();
    const sid = A.state.session.id;
    const images = A.state.attachments.map((a) => ({ media_type: a.media_type, data: a.data }));
    const userMsgObj = {
      role: "user",
      content: images.length
        ? [{ type: "text", text }].concat(images.map((i) => ({ type: "image", media_type: i.media_type, data: i.data })))
        : text,
    };
    A.state.session.messages.push(userMsgObj);
    input.value = "";
    autoSize(input);
    A.clearAttachments();
    const host = A.$("#messages");
    if (host.querySelector(".welcome")) host.innerHTML = "";
    host.appendChild(userMsg(userMsgObj));
    scrollBottom(true);

    const live = startLiveAssistant();
    A.setStreaming(true);
    A.state.lastAssistant = live;

    let buffer = "";
    let reasoning = "";
    let usage = null;
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: sid, text, images,
          mode: (A.state.config && A.state.config.mode) || "build",
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "请求失败");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let sseBuf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        sseBuf += decoder.decode(value, { stream: true });
        const parts = sseBuf.split("\n\n");
        sseBuf = parts.pop();
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch (e) { continue; }
          handleEvent(ev, live, { append: (t) => { buffer += t; }, });
          if (ev.type === "reasoning") reasoning += ev.text;
          if (ev.type === "usage") usage = ev.usage;
          if (ev.type === "done" || ev.type === "end") { /* handled */ }
        }
      }
    } catch (e) {
      live.content.appendChild(A.h(`<div class="notice" style="color:#ff8f8f;font-size:12.5px">${A.esc(e.message)}</div>`));
      A.toast(e.message, "err");
    } finally {
      finalizeLive(live, buffer, reasoning);
      A.setStreaming(false);
      try {
        const data = await A.api("/api/session/" + sid);
        A.state.session = data.session;
        A.renderSessions();
        A.renderTodos();
        A.$("#view-title").textContent = data.session.title || "会话";
      } catch (e) {}
      scrollBottom();
    }
  };

  function startLiveAssistant() {
    const host = A.$("#messages");
    const wrap = A.h(`<div class="msg assistant"><div class="avatar">AI</div><div class="content">
      <div class="meta">AiCode <span class="live-state">生成中…</span></div></div></div>`);
    const content = wrap.querySelector(".content");
    host.appendChild(wrap);
    scrollBottom(true);
    return { wrap, content, bubble: null, reasoningEl: null, text: "", reasoning: "", tools: {} };
  }

  function handleEvent(ev, live, ctx) {
    if (ev.type === "text") {
      live.text += ev.text;
      if (!live.bubble) {
        live.bubble = document.createElement("div");
        live.bubble.className = "bubble md cursor";
        live.content.appendChild(live.bubble);
      }
      scheduleRender(live);
      scrollBottom();
    } else if (ev.type === "reasoning") {
      if (!live.reasoningEl) {
        live.reasoningEl = A.h(`<details class="reasoning" open><summary>${A.t("thinking")}</summary><div class="rtext"></div></details>`);
        live.content.insertBefore(live.reasoningEl, live.bubble);
      }
      live.reasoning += ev.text;
      live.reasoningEl.querySelector(".rtext").textContent = live.reasoning;
      scrollBottom();
    } else if (ev.type === "tool_call") {
      const card = toolCard(ev.id, ev.name, ev.args, "", true, false);
      live.content.appendChild(card);
      live.tools[ev.id] = card;
      scrollBottom();
    } else if (ev.type === "tool_result") {
      const card = live.tools[ev.id];
      if (card) {
        card.classList.remove("running");
        card.classList.add(ev.error ? "err" : "ok");
        card.querySelector(".tc-out").textContent = ev.content || "";
        card.querySelector(".tc-sum").textContent = toolSummary(ev.name, card._args);
      }
      scrollBottom();
    } else if (ev.type === "approval") {
      showApproval(ev);
    } else if (ev.type === "todos") {
      if (A.state.session) A.state.session.todos = ev.todos;
      A.renderTodos();
    } else if (ev.type === "terminal_open") {
      A.toast("Agent 已打开终端：" + (ev.title || ev.id));
      A.state.terminals.push({ id: ev.id, title: ev.title || "终端", alive: true });
      A.renderTermTabs();
    } else if (ev.type === "notice") {
      live.content.appendChild(A.h(`<div class="notice muted" style="font-size:12px;margin:4px 0">${A.esc(ev.text)}</div>`));
    } else if (ev.type === "error") {
      live.content.appendChild(A.h(`<div class="notice" style="color:#ff8f8f;font-size:12.5px">${A.esc(ev.text)}</div>`));
    } else if (ev.type === "title") {
      A.$("#view-title").textContent = ev.title;
    }
  }

  let renderTimer = null;
  function scheduleRender(live) {
    if (renderTimer) return;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      if (!live.bubble) return;
      live.bubble.innerHTML = A.renderMarkdown(live.text);
      A.decorateMarkdown(live.bubble);
      scrollBottom();
    }, 110);
  }

  function finalizeLive(live, buffer, reasoning) {
    if (live.bubble) {
      live.bubble.classList.remove("cursor");
      live.bubble.innerHTML = A.renderMarkdown(live.text);
      A.decorateMarkdown(live.bubble);
    }
    const st = live.wrap.querySelector(".live-state");
    if (st) st.remove();
    // 去掉空 assistant 容器
    if (!live.text && !live.content.querySelector(".tool-card") && !live.content.querySelector(".notice") && !live.reasoningEl) {
      live.wrap.remove();
    }
    scrollBottom();
  }

  A.setStreaming = function (on) {
    A.state.streaming = on;
    A.$("#btn-send").classList.toggle("hidden", on);
    A.$("#btn-stop").classList.toggle("hidden", !on);
    A.$("#input").disabled = false;
    A.$$("#mode-select button").forEach((b) => { b.disabled = on; });
    A.$("#model-select").disabled = on;
  };

  A.stopStreaming = async function () {
    if (!A.state.session) return;
    try {
      await A.api("/api/stop", { method: "POST", body: { sessionId: A.state.session.id } });
      A.toast("已请求停止");
    } catch (e) { A.toast(e.message, "err"); }
  };

  // ---------------------------------------------------------------- 审批
  function showApproval(ev) {
    A.$("#approval-body").innerHTML = `
      <div style="font-size:13px">Agent 请求执行 <span class="approve-tool">${A.esc(ev.tool)}</span>：${A.esc(ev.summary || "")}</div>
      ${ev.detail ? `<div class="approve-detail">${A.esc(ev.detail)}</div>` : ""}
      <div class="muted" style="font-size:11px;margin-top:8px">模式：${A.esc(A.state.config.mode || "build")} · 可在设置中调整工具权限</div>`;
    const foot = A.$("#approval-foot");
    foot.innerHTML = `
      <button class="ghost-btn" data-a="deny">${A.t("deny")}</button>
      <button class="ghost-btn" data-a="always">${A.t("always")}</button>
      <button class="primary-btn" data-a="allow">${A.t("allow")}</button>`;
    A.openModal("approval-modal");
    foot.querySelectorAll("button").forEach((b) => {
      b.onclick = async () => {
        const action = b.dataset.a;
        A.closeModal("approval-modal");
        try {
          await A.api("/api/approve", {
            method: "POST",
            body: { id: ev.id, allowed: action !== "deny", always: action === "always", tool: ev.tool },
          });
        } catch (e) { A.toast(e.message, "err"); }
      };
    });
  }

  // ---------------------------------------------------------------- 输入区
  function autoSize(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }

  A.addAttachment = function (file) {
    if (!file || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result);
      const [head, data] = url.split(",");
      const media = (head.match(/data:([^;]+)/) || [])[1] || "image/png";
      A.state.attachments.push({ media_type: media, data, url });
      renderAttachments();
    };
    reader.readAsDataURL(file);
  };

  function renderAttachments() {
    const box = A.$(".composer-box");
    let strip = A.$("#attachments");
    if (!strip) {
      strip = A.h(`<div id="attachments" style="display:flex;gap:6px;flex-wrap:wrap;padding:2px 2px 6px"></div>`);
      box.insertBefore(strip, box.firstChild);
    }
    strip.innerHTML = "";
    A.state.attachments.forEach((a, i) => {
      const el = A.h(`<div style="position:relative"><img src="${a.url}" style="height:52px;border-radius:7px;border:1px solid var(--border);display:block">
        <button style="position:absolute;right:2px;top:2px;width:16px;height:16px;border-radius:50%;background:rgba(0,0,0,.65);color:#fff;font-size:10px;line-height:1">×</button></div>`);
      el.querySelector("button").onclick = () => { A.state.attachments.splice(i, 1); renderAttachments(); };
      strip.appendChild(el);
    });
    if (!A.state.attachments.length) strip.remove();
  }

  A.clearAttachments = function () {
    A.state.attachments = [];
    renderAttachments();
  };

  A.setMode = function (mode) {
    if (A.state.config) A.state.config.mode = mode;
    A.$$("#mode-select button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    const hint = A.$("#composer-hint");
    if (hint) hint.textContent = "模式：" + (A.t("mode." + mode) || mode.toUpperCase());
    A.api("/api/config", { method: "POST", body: { config: Object.assign({}, A.state.config, { mode }) } }).catch(() => {});
  };

  A.updateModeButtons = function () {
    const mode = (A.state.config && A.state.config.mode) || "build";
    A.$$("#mode-select button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    const hint = A.$("#composer-hint");
    if (hint) hint.textContent = "模式：" + (A.t("mode." + mode) || mode.toUpperCase());
  };

  A.bindComposer = function () {
    const input = A.$("#input");
    input.addEventListener("input", () => autoSize(input));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        A.sendMessage();
      }
    });
    input.addEventListener("paste", (e) => {
      const items = Array.from(e.clipboardData.items || []);
      items.forEach((it) => {
        if (it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) A.addAttachment(f);
        }
      });
    });
    A.$("#btn-send").onclick = () => A.sendMessage();
    A.$("#btn-stop").onclick = () => A.stopStreaming();
    A.$("#btn-attach").onclick = () => A.$("#file-input").click();
    A.$("#file-input").onchange = (e) => {
      Array.from(e.target.files || []).forEach((f) => A.addAttachment(f));
      e.target.value = "";
    };
    A.$$("#mode-select button").forEach((b) => {
      b.onclick = () => A.setMode(b.dataset.mode);
    });
    A.$("#model-select").onchange = (e) => {
      const [pid, mid] = e.target.value.split("::");
      A.state.config.active = { providerId: pid, model: mid };
      A.api("/api/config", { method: "POST", body: { config: A.state.config } })
        .then((d) => { A.state.config = d.config; A.toast("已切换模型", "ok"); })
        .catch((err) => A.toast(err.message, "err"));
    };
    document.addEventListener("dragover", (e) => e.preventDefault());
    document.addEventListener("drop", (e) => {
      e.preventDefault();
      Array.from(e.dataTransfer.files || []).forEach((f) => A.addAttachment(f));
    });
    A.$$("#view-chat").forEach((v) => v.addEventListener("dragover", (e) => e.preventDefault()));
  };
})();
