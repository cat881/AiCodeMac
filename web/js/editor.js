/* 文件树、编辑器、预览 */
(function () {
  const A = window.A;

  A.loadTree = async function () {
    try {
      const data = await A.api("/api/fs/tree?depth=6");
      A.state.tree = data.tree;
      A.renderTree();
    } catch (e) {
      A.$("#file-tree").innerHTML = `<div class="empty-state"><div>${A.esc(e.message)}</div></div>`;
    }
  };

  A.renderTree = function () {
    const host = A.$("#file-tree");
    if (!host || !A.state.tree) return;
    host.innerHTML = "";
    const root = A.state.tree;
    const build = (node, depth) => {
      const wrap = document.createElement("div");
      if (node.dir) {
        const row = A.h(`<div class="tree-row" style="padding-left:${6 + depth * 12}px">
          <span class="caret">${A.state.expanded[node.path] === false ? "▸" : "▾"}</span>
          <span class="tree-icon">${A.icon("folder")}</span>
          <span class="fname">${A.esc(node.name)}</span></div>`);
        row.onclick = () => {
          A.state.expanded[node.path] = A.state.expanded[node.path] === false;
          A.renderTree();
        };
        wrap.appendChild(row);
        if (A.state.expanded[node.path] !== false) {
          (node.children || []).forEach((c) => wrap.appendChild(build(c, depth + 1)));
        }
      } else {
        const active = A.state.activeTab && A.state.activeTab.path === node.path;
        const row = A.h(`<div class="tree-row ${active ? "active" : ""}" style="padding-left:${6 + depth * 12}px" title="${A.esc(node.path)}">
          <span class="caret"></span><span class="tree-icon">·</span>
          <span class="fname">${A.esc(node.name)}</span></div>`);
        row.onclick = () => A.openFile(node.path);
        wrap.appendChild(row);
      }
      return wrap;
    };
    if (root.children) root.children.forEach((c) => host.appendChild(build(c, 0)));
  };

  A.tabFor = function (path) {
    return A.state.editorTabs.find((t) => t.path === path);
  };

  A.openFile = async function (path, line) {
    A.setView("files");
    const existing = A.tabFor(path);
    if (existing) {
      A.state.activeTab = existing;
      A.renderTabs();
      A.mountEditor(existing, line);
      return;
    }
    try {
      const data = await A.api("/api/fs/read?path=" + encodeURIComponent(path));
      const tab = { path: data.file.path, content: data.file.content, lang: data.file.lang, dirty: false };
      A.state.editorTabs.push(tab);
      A.state.activeTab = tab;
      A.renderTabs();
      A.mountEditor(tab, line);
    } catch (e) {
      A.toast(e.message, "err");
    }
  };

  A.renderTabs = function () {
    const host = A.$("#editor-tabs");
    if (!host) return;
    host.innerHTML = "";
    A.state.editorTabs.forEach((t) => {
      const el = A.h(`<div class="editor-tab ${t === A.state.activeTab ? "active" : ""}">
        <span>${A.esc(t.path.split("/").pop())}${t.dirty ? " •" : ""}</span>
        <button class="x">×</button></div>`);
      el.onclick = (e) => {
        if (e.target.classList.contains("x")) {
          A.closeTab(t);
          return;
        }
        A.state.activeTab = t;
        A.renderTabs();
        A.mountEditor(t);
      };
      host.appendChild(el);
    });
    const toolbar = A.$("#editor-toolbar");
    if (toolbar) toolbar.classList.toggle("hidden", !A.state.activeTab);
    if (A.state.activeTab) {
      A.$("#editor-path").textContent = A.state.activeTab.path + (A.state.activeTab.dirty ? "（未保存）" : "");
      const isMd = A.state.activeTab.lang === "markdown";
      A.$("#btn-preview").classList.toggle("hidden", !isMd);
    }
  };

  A.closeTab = async function (tab) {
    if (tab.dirty) {
      const ok = await A.confirm("关闭文件", `<p>${A.esc(tab.path)} 有未保存的修改，确定关闭？</p>`);
      if (!ok) return;
    }
    A.state.editorTabs = A.state.editorTabs.filter((t) => t !== tab);
    if (A.state.activeTab === tab) {
      A.state.activeTab = A.state.editorTabs[A.state.editorTabs.length - 1] || null;
    }
    A.renderTabs();
    if (A.state.activeTab) A.mountEditor(A.state.activeTab);
    else {
      A.$("#editor-host").innerHTML = `<div class="empty-state"><div class="empty-icon">⌘</div><div>${A.t("emptyFile")}</div></div>`;
      A.$("#editor-toolbar").classList.add("hidden");
      A.state.cm = null;
    }
  };

  A.mountEditor = async function (tab, line) {
    const host = A.$("#editor-host");
    if (!host) return;
    A.state.preview = false;
    host.innerHTML = "";
    await ensureCMMode(tab.lang);
    const cm = CodeMirror(host, {
      value: tab.content,
      mode: tab.lang || "clike",
      lineNumbers: true,
      lineWrapping: false,
      indentUnit: 4,
      tabSize: 4,
      autofocus: false,
      styleActiveLine: true,
    });
    A.state.cm = cm;
    cm.on("change", () => {
      if (tab.content !== cm.getValue()) {
        tab.content = cm.getValue();
        tab.dirty = true;
        A.$("#editor-path").textContent = tab.path + "（未保存）";
        A.renderTabs();
      }
    });
    setTimeout(() => {
      cm.refresh();
      if (line) {
        const l = Math.max(0, Math.min(line - 1, cm.lineCount() - 1));
        cm.setCursor({ line: l, ch: 0 });
        cm.scrollIntoView({ line: l, ch: 0 }, 160);
        cm.addLineClass(l, "background", "cm-jump-line");
        setTimeout(() => cm.removeLineClass(l, "background", "cm-jump-line"), 2200);
      }
    }, 30);
  };

  A.saveFile = async function () {
    const tab = A.state.activeTab;
    if (!tab) return;
    try {
      await A.api("/api/fs/write", { method: "POST", body: { path: tab.path, content: tab.content } });
      tab.dirty = false;
      A.renderTabs();
      A.toast("已保存 " + tab.path, "ok");
      A.loadTree();
      if (A.state.view === "git" && window.renderGit) window.renderGit();
    } catch (e) {
      A.toast(e.message, "err");
    }
  };

  A.togglePreview = function () {
    const tab = A.state.activeTab;
    if (!tab || tab.lang !== "markdown") return;
    A.state.preview = !A.state.preview;
    const host = A.$("#editor-host");
    let overlay = host.querySelector(".md-preview");
    if (A.state.preview) {
      if (!overlay) {
        overlay = document.createElement("div");
        overlay.className = "md-preview";
        host.appendChild(overlay);
      }
      overlay.innerHTML = A.renderMarkdown(tab.content);
      A.decorateMarkdown(overlay);
      A.state.cm && A.state.cm.getWrapperElement().style.setProperty("display", "none");
    } else if (overlay) {
      overlay.remove();
      A.state.cm && A.state.cm.getWrapperElement().style.removeProperty("display");
      A.state.cm && A.state.cm.refresh();
    }
  };

  A.renderInspector = function () {
    const body = A.$("#inspector-body");
    if (!body) return;
    const tab = A.state.inspectorTab;
    if (tab === "terminal") {
      body.innerHTML = `<div class="settings-content">
        <div class="section-title">终端会话</div>
        <div class="section-desc">在终端页管理中，共 ${A.state.terminals.length} 个会话。</div>
        <button class="primary-btn" id="insp-term-new">新建终端</button>
        <button class="ghost-btn" id="insp-term-go" style="margin-left:8px">前往终端页</button>
      </div>`;
      A.$("#insp-term-new").onclick = () => { A.createTerminal(); A.setView("terminal"); };
      A.$("#insp-term-go").onclick = () => A.setView("terminal");
      return;
    }
    body.innerHTML = `<div class="settings-content">
      <div class="section-title">快速打开</div>
      <div class="section-desc">已打开 ${A.state.editorTabs.length} 个文件</div>
      <div id="insp-files"></div>
      <div style="margin-top:12px"><input id="insp-path" placeholder="输入文件路径后回车…"></div>
    </div>`;
    const list = A.$("#insp-files");
    A.state.editorTabs.forEach((t) => {
      const row = A.h(`<div class="tree-row"><span class="tree-icon">·</span><span class="fname">${A.esc(t.path)}</span></div>`);
      row.onclick = () => { A.setView("files"); A.openFile(t.path); };
      list.appendChild(row);
    });
    A.$("#insp-path").onkeydown = (e) => {
      if (e.key === "Enter" && e.target.value.trim()) A.openFile(e.target.value.trim());
    };
  };

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
      if (A.state.view === "files") {
        e.preventDefault();
        A.saveFile();
      }
    }
  });
})();
