/* 多标签 PTY 终端（xterm.js） */
(function () {
  const A = window.A;
  A.termInstances = {};
  A.termInstances = {};

  function b64utf8(s) {
    const bytes = new TextEncoder().encode(s);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  function newTermTheme() {
    return {
      background: "#0a0c0f", foreground: "#d6deea", cursor: "#4f8cff",
      selectionBackground: "rgba(79,140,255,.35)", black: "#1b1f27", red: "#ff6b6b",
      green: "#3ecf8e", yellow: "#ffb44d", blue: "#5b9dff", magenta: "#c792ea",
      cyan: "#4dd0e1", white: "#d6deea", brightBlack: "#5c6675", brightRed: "#ff8f8f",
      brightGreen: "#7ee0a8", brightYellow: "#ffd08a", brightBlue: "#8bb8ff",
      brightMagenta: "#e0b0ff", brightCyan: "#84e4f2", brightWhite: "#ffffff",
    };
  }

  A.renderTermTabs = function () {
    const host = A.$("#term-tabs");
    if (!host) return;
    host.innerHTML = "";
    A.state.terminals.forEach((t) => {
      const el = A.h(`<div class="term-tab ${t.id === A.state.activeTerm ? "active" : ""}">
        <span>${A.esc(t.title || t.id)}</span><button class="x">×</button></div>`);
      el.onclick = (e) => {
        if (e.target.classList.contains("x")) return A.closeTerminal(t.id);
        A.activateTerminal(t.id);
      };
      host.appendChild(el);
    });
  };

  A.activateTerminal = function (id) {
    A.state.activeTerm = id;
    A.renderTermTabs();
    const host = A.$("#term-host");
    Array.from(host.children).forEach((c) => c.classList.add("hidden"));
    const inst = A.termInstances[id];
    if (inst) {
      inst.wrap.classList.remove("hidden");
      setTimeout(() => { inst.fit.fit(); inst.term.focus(); }, 20);
    } else {
      const t = A.state.terminals.find((x) => x.id === id);
      if (t) A.attachTerminal(t);
    }
  };

  A.createTerminal = async function (command, title) {
    try {
      const data = await A.api("/api/terms", { method: "POST", body: { title: title || "终端", command: command || "" } });
      const t = data.terminal;
      A.state.terminals.push(t);
      A.state.activeTerm = t.id;
      A.renderTermTabs();
      A.attachTerminal(t);
      A.setView("terminal");
      return t;
    } catch (e) {
      A.toast(e.message, "err");
    }
  };

  A.attachTerminal = function (t) {
    const host = A.$("#term-host");
    const wrap = document.createElement("div");
    wrap.className = "term-inst";
    wrap.dataset.id = t.id;
    host.innerHTML = "";
    Array.from(host.querySelectorAll(".empty-state")).forEach((n) => n.remove());
    host.appendChild(wrap);

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 12.5,
      fontFamily: 'ui-monospace, "SF Mono", Menlo, Monaco, monospace',
      theme: newTermTheme(),
      scrollback: 8000,
      allowProposedApi: true,
      macOptionIsMeta: true,
    });
    const fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(wrap);
    setTimeout(() => { try { fit.fit(); } catch (e) {} }, 30);

    term.onData((data) => {
      A.api("/api/term/input", { method: "POST", body: { id: t.id, data_b64: b64utf8(data) } }).catch(() => {});
    });
    term.onResize(({ cols, rows }) => {
      A.api("/api/term/resize", { method: "POST", body: { id: t.id, cols, rows } }).catch(() => {});
    });

    const es = new EventSource("/api/term/stream?id=" + t.id + "&offset=0");
    es.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "data") {
        const bin = atob(msg.data);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        term.write(bytes);
      } else if (msg.type === "exit") {
        term.write("\r\n\x1b[90m[进程已退出]\x1b[0m\r\n");
        es.close();
      }
    };
    es.onerror = () => {};

    A.termInstances[t.id] = { term, fit, es, wrap };
    setTimeout(() => {
      if (A.state.view === "terminal") {
        fit.fit();
        term.focus();
      }
    }, 60);
    A.state.terminals = A.state.terminals.map((x) => x.id === t.id ? Object.assign({}, x, { offset: 0 }) : x);
  };

  A.closeTerminal = async function (id) {
    try { await A.api("/api/term/close", { method: "POST", body: { id } }); } catch (e) {}
    const inst = A.termInstances[id];
    if (inst) {
      inst.es.close();
      inst.term.dispose();
      inst.wrap.remove();
      delete A.termInstances[id];
    }
    A.state.terminals = A.state.terminals.filter((t) => t.id !== id);
    if (A.state.activeTerm === id) {
      A.state.activeTerm = A.state.terminals.length ? A.state.terminals[A.state.terminals.length - 1].id : null;
    }
    A.renderTermTabs();
    if (A.state.activeTerm) A.activateTerminal(A.state.activeTerm);
    else {
      const host = A.$("#term-host");
      host.innerHTML = `<div class="empty-state"><div class="empty-icon">$_</div><div>${A.t("emptyTerm")}</div></div>`;
    }
  };

  A.fitTerminals = function () {
    const inst = A.termInstances[A.state.activeTerm];
    if (inst) setTimeout(() => { try { inst.fit.fit(); inst.term.focus(); } catch (e) {} }, 30);
  };

  window.addEventListener("resize", A.debounce(() => {
    if (A.state.view === "terminal") A.fitTerminals();
  }, 200));
})();
