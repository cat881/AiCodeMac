/* 基础工具、状态、i18n、主题与 API */
(function () {
  const I18N = {
    zh: {
      chat: "会话", files: "文件", git: "Git", terminal: "终端", stats: "统计", settings: "设置",
      newSession: "新建会话", search: "搜索会话…", workspace: "工作区", send: "发送", stop: "停止",
      emptyWelcome: "把任务交给 AiCode", emptySub: "读取代码、修改文件、运行命令，一切都在本地完成。",
      placeholder: "描述任务，或粘贴图片…（Enter 发送，Shift+Enter 换行）",
      composerFoot: "AiCode 可能会修改工作区文件；写操作会按模式请求授权，并生成可回滚的检查点。",
      approval: "需要授权", allow: "允许", deny: "拒绝", always: "始终允许",
      thinking: "思考过程", toolCall: "工具调用", result: "结果", retry: "重试",
      noSession: "没有会话", untitled: "新会话", save: "保存", preview: "预览", close: "关闭",
      cancel: "取消", confirm: "确定", copy: "复制", copied: "已复制", emptyTerm: "还没有终端，点击右上角新建",
      emptyFile: "从左侧选择一个文件开始编辑", tokens: "Token", cost: "费用", calls: "调用次数",
      mode: { build: "正常开发", plan: "只读规划", auto: "全自动" },
    },
    en: {
      chat: "Chat", files: "Files", git: "Git", terminal: "Terminal", stats: "Usage", settings: "Settings",
      newSession: "New chat", search: "Search chats…", workspace: "Workspace", send: "Send", stop: "Stop",
      emptyWelcome: "Hand the task to AiCode", emptySub: "Read code, edit files and run commands — all locally.",
      placeholder: "Describe a task, or paste an image… (Enter to send, Shift+Enter for newline)",
      composerFoot: "AiCode may modify workspace files; write actions ask for approval and create rollback checkpoints.",
      approval: "Permission required", allow: "Allow", deny: "Deny", always: "Always allow",
      thinking: "Reasoning", toolCall: "Tool call", result: "Result", retry: "Retry",
      noSession: "No chats", untitled: "New chat", save: "Save", preview: "Preview", close: "Close",
      cancel: "Cancel", confirm: "Confirm", copy: "Copy", copied: "Copied", emptyTerm: "No terminal yet. Create one from the top-right.",
      emptyFile: "Select a file on the left to start editing", tokens: "Tokens", cost: "Cost", calls: "Calls",
      mode: { build: "Build", plan: "Plan", auto: "Auto" },
    },
  };

  const A = {
    state: {
      config: null,
      sessions: [],
      session: null,
      view: "chat",
      streaming: false,
      aborter: null,
      attachments: [],
      terminals: [],
      activeTerm: null,
      tree: null,
      editorTabs: [],
      activeTab: null,
      cm: null,
      dirty: false,
      preview: false,
      inspectorTab: "files",
      sessionQuery: "",
      expanded: {},
      loadedModes: {},
      pendingMode: null,
      lastAssistant: null,
    },

    t(key) {
      const lang = (this.state.config && this.state.config.language) || "zh";
      const dict = I18N[lang] || I18N.zh;
      const parts = key.split(".");
      let v = dict;
      for (const p of parts) v = v && v[p];
      return v == null ? key : v;
    },

    esc(s) {
      return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
      })[c]);
    },

    h(html) {
      const tpl = document.createElement("template");
      tpl.innerHTML = html.trim();
      return tpl.content.firstElementChild;
    },

    icon(name, cls) {
      return `<svg class="${cls || ""}"><use href="#i-${name}"/></svg>`;
    },

    $(sel, root) { return (root || document).querySelector(sel); },
    $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); },

    async api(path, opts) {
      opts = opts || {};
      const init = { method: opts.method || "GET", headers: {} };
      if (opts.body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
      }
      const res = await fetch(path, init);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        const err = new Error(data.error || ("HTTP " + res.status));
        err.data = data;
        throw err;
      }
      return data;
    },

    toast(msg, type) {
      const wrap = this.$("#toast-wrap");
      const el = this.h(`<div class="toast ${type || ""}">${this.esc(msg)}</div>`);
      wrap.appendChild(el);
      setTimeout(() => {
        el.style.opacity = "0";
        el.style.transition = "opacity .2s";
        setTimeout(() => el.remove(), 220);
      }, type === "err" ? 5200 : 2600);
    },

    confirm(title, message) {
      return new Promise((resolve) => {
        this.$("#confirm-title").textContent = title;
        this.$("#confirm-body").innerHTML = message;
        this.openModal("confirm-modal");
        const ok = this.$("#confirm-ok");
        const cancel = this.$("#confirm-cancel");
        const done = (v) => {
          this.closeModal("confirm-modal");
          ok.onclick = null;
          cancel.onclick = null;
          resolve(v);
        };
        ok.onclick = () => done(true);
        cancel.onclick = () => done(false);
      });
    },

    openModal(id) { this.$("#" + id).classList.remove("hidden"); },
    closeModal(id) { this.$("#" + id).classList.add("hidden"); },

    fmtNum(n) {
      n = Number(n || 0);
      if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
      if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
      return String(n);
    },

    fmtMoney(n) {
      n = Number(n || 0);
      if (n === 0) return "$0";
      if (n < 0.01) return "$" + n.toFixed(4);
      return "$" + n.toFixed(2);
    },

    fmtTime(ts) {
      if (!ts) return "";
      const d = new Date(ts);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const hm = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
      if (sameDay) return hm;
      return (d.getMonth() + 1) + "/" + d.getDate() + " " + hm;
    },

    debounce(fn, ms) {
      let t;
      return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn.apply(null, args), ms || 250);
      };
    },

    async copy(text) {
      try {
        await navigator.clipboard.writeText(text);
        this.toast(this.t("copied"), "ok");
      } catch (e) {
        this.toast("复制失败", "err");
      }
    },

    applyTheme() {
      const cfg = this.state.config || {};
      const theme = cfg.theme || "dark";
      document.documentElement.dataset.theme = theme;
      document.documentElement.style.setProperty("--accent", cfg.accent || "#4f8cff");
      document.documentElement.style.setProperty("--accent-soft",
        (cfg.accent || "#4f8cff") + "24");
      const glyph = this.$("#theme-glyph");
      if (glyph) glyph.textContent = theme === "dark" ? "◐" : "◑";
      const hl = this.$("#hljs-theme");
      if (hl) hl.href = theme === "dark" ? "/vendor/hljs-dark.css" : "/vendor/hljs-light.css";
      if (cfg.fontSize) document.body.style.fontSize = cfg.fontSize + "px";
      const dark = theme === "dark";
      const cmTheme = this.$("#cm-theme");
      if (cmTheme) cmTheme.remove();
    },

    buildModelOptions() {
      const cfg = this.state.config || {};
      const sel = this.$("#model-select");
      if (!sel) return;
      const active = cfg.active || {};
      sel.innerHTML = "";
      let found = false;
      (cfg.providers || []).forEach((p) => {
        const group = document.createElement("optgroup");
        group.label = p.name;
        (p.models || []).forEach((m) => {
          const opt = document.createElement("option");
          opt.value = p.id + "::" + m.id;
          opt.textContent = m.name || m.id;
          if (active.providerId === p.id && active.model === m.id) { opt.selected = true; found = true; }
          group.appendChild(opt);
        });
        if (group.children.length) sel.appendChild(group);
      });
      if (!found && sel.options.length) {
        sel.options[0].selected = true;
        const [pid, mid] = sel.value.split("::");
        cfg.active = { providerId: pid, model: mid };
      }
      if (!sel.options.length) {
        const opt = document.createElement("option");
        opt.textContent = "未配置模型";
        opt.value = "";
        sel.appendChild(opt);
      }
    },

    async saveConfig(patch) {
      const cfg = Object.assign({}, this.state.config, patch || {});
      const data = await this.api("/api/config", { method: "POST", body: { config: cfg } });
      this.state.config = data.config;
      this.applyTheme();
      this.buildModelOptions();
      this.applyStaticI18n();
      return data.config;
    },

    applyStaticI18n() {
      const t = (k) => this.t(k);
      const input = this.$("#input");
      if (input) input.placeholder = t("placeholder");
      const hint = this.$(".composer-foot");
      if (hint) hint.textContent = t("composerFoot");
      const search = this.$("#session-search");
      if (search) search.placeholder = t("search");
      const wsLabel = this.$(".workspace-chip");
      if (wsLabel) wsLabel.title = t("workspace");
      this.$("#btn-new-session") && this.$("#btn-new-session").setAttribute("title", t("newSession"));
      this.$$(".rail-btn[data-view]").forEach((b) => {
        b.title = t(b.dataset.view === "chat" ? "chat" : b.dataset.view);
      });
      this.$("#btn-settings").title = t("settings");
      this.$("#view-title").textContent = t(this.state.view);
    },
  };

  window.A = A;
})();
