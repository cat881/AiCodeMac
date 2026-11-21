/* 应用入口：导航、状态加载、全局事件 */
(function () {
  const A = window.A;

  A.setView = function (view) {
    A.state.view = view;
    A.$$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
    A.$$(".rail-btn[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    const titles = { chat: null, files: "文件", git: "Git", terminal: "终端", stats: "统计" };
    if (view === "chat") A.$("#view-title").textContent = (A.state.session && A.state.session.title) || "会话";
    else A.$("#view-title").textContent = titles[view] || view;
    if (window.innerWidth <= 900) document.getElementById("app").classList.remove("sidebar-open");
    if (view === "files") {
      if (!A.state.tree) A.loadTree();
      if (A.state.activeTab && A.state.cm) setTimeout(() => A.state.cm.refresh(), 30);
    }
    if (view === "git") A.loadGit();
    if (view === "stats") A.loadStats();
    if (view === "terminal") {
      A.renderTermTabs();
      if (A.state.activeTerm) A.activateTerminal(A.state.activeTerm);
      A.fitTerminals();
    }
  };

  A.afterWorkspaceChange = function (ws) {
    A.$("#workspace-name").textContent = shortPath(ws);
    A.state.tree = null;
    A.state.editorTabs = [];
    A.state.activeTab = null;
    A.$("#editor-tabs").innerHTML = "";
    A.$("#editor-host").innerHTML = `<div class="empty-state"><div class="empty-icon">⌘</div><div>${A.t("emptyFile")}</div></div>`;
    A.$("#editor-toolbar").classList.add("hidden");
    A.loadTree();
    A.loadGit();
    A.$("#file-tree").innerHTML = "";
  };

  function shortPath(p) {
    if (!p) return "";
    const home = A.state.home || "";
    if (home && p === home) return "~";
    if (home && p.startsWith(home + "/")) return "~" + p.slice(home.length);
    const parts = p.split("/").filter(Boolean);
    return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : p;
  }

  async function init() {
    A.bindComposer();
    try {
      const st = await A.api("/api/state");
      A.state.config = st.config;
      A.state.sessions = st.sessions;
      A.state.terminals = st.terminals || [];
      A.state.home = st.home;
      A.state.version = st.version;
      A.applyTheme();
      A.buildModelOptions();
      A.applyStaticI18n();
      A.updateModeButtons();
      A.$("#workspace-name").textContent = shortPath(st.workspace);
      A.renderSessions();
      A.renderTermTabs();
      if (st.sessions.length) {
        await A.loadSession(st.sessions[0].id);
      } else {
        A.renderChat();
        A.setView("chat");
      }
      if (st.mcp && st.mcp.length) {
        console.log("MCP:", st.mcp);
      }
    } catch (e) {
      A.toast("初始化失败：" + e.message, "err");
    }

    A.$$(".rail-btn[data-view]").forEach((b) => {
      b.onclick = () => A.setView(b.dataset.view);
    });
    A.$("#btn-new-session").onclick = () => A.newSession();
    A.$("#session-search").oninput = (e) => {
      A.state.sessionQuery = e.target.value.trim();
      A.renderSessions();
    };
    A.$("#btn-theme").onclick = async () => {
      const theme = (A.state.config.theme === "dark") ? "light" : "dark";
      A.state.config.theme = theme;
      A.applyTheme();
      try { await A.saveConfig({ theme }); } catch (e) {}
    };
    A.$("#btn-settings").onclick = () => A.openSettings();
    A.$("#workspace-chip").onclick = async () => {
      try {
        const r = await A.api("/api/workspace", { method: "POST", body: { path: "__pick__" } });
        if (r.cancelled) return;
        A.state.config.workspace = r.workspace;
        A.afterWorkspaceChange(r.workspace);
        A.toast("工作区已切换", "ok");
      } catch (e) { A.toast(e.message, "err"); }
    };
    A.$("#btn-tree-refresh").onclick = () => A.loadTree();
    A.$("#btn-save").onclick = () => A.saveFile();
    A.$("#btn-preview").onclick = () => A.togglePreview();
    A.$("#btn-new-term").onclick = () => A.createTerminal();
    A.$("#btn-sidebar").onclick = () => document.getElementById("app").classList.toggle("sidebar-open");
    A.$("#btn-inspector").onclick = () => {
      const app = document.getElementById("app");
      app.classList.toggle("inspector-open");
      A.$("#inspector").classList.toggle("hidden", !app.classList.contains("inspector-open"));
      A.renderInspector();
    };
    A.$("#btn-close-inspector").onclick = () => {
      document.getElementById("app").classList.remove("inspector-open");
      A.$("#inspector").classList.add("hidden");
    };
    A.$$("#inspector-tabs button").forEach((b) => {
      b.onclick = () => {
        A.state.inspectorTab = b.dataset.tab;
        A.$$("#inspector-tabs button").forEach((x) => x.classList.toggle("active", x === b));
        A.renderInspector();
      };
    });
    A.$$("[data-close]").forEach((b) => {
      b.onclick = () => A.closeModal(b.dataset.close);
    });
    A.$("#settings-modal").addEventListener("click", (e) => {
      if (e.target.id === "settings-modal") A.closeModal("settings-modal");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        ["settings-modal", "approval-modal", "confirm-modal"].forEach((id) => A.closeModal(id));
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        A.newSession();
      }
    });
    document.addEventListener("click", (e) => {
      const link = e.target.closest("a.file-link");
      if (link) {
        e.preventDefault();
        A.openFile(link.dataset.path, Number(link.dataset.line || 1));
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
