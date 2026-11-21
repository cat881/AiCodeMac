/* Git 面板 */
(function () {
  const A = window.A;
  const state = { status: null, log: [], branches: [], diff: "", selected: null, user: null, tab: "changes" };

  function diffHtml(text) {
    if (!text) return `<div class="empty-state"><div>选择文件查看差异</div></div>`;
    return text.split("\n").map((line) => {
      const cls = line.startsWith("+++") || line.startsWith("---") ? "hunk"
        : line.startsWith("+") ? "add"
          : line.startsWith("-") ? "del"
            : line.startsWith("@@") ? "hunk" : "";
      return `<div class="${cls}">${A.esc(line) || " "}</div>`;
    }).join("");
  }

  function statusClass(s) {
    return (s || "?").charAt(0);
  }

  A.loadGit = async function () {
    try {
      const st = await A.api("/api/git/status");
      if (!st.repo) {
        state.status = null;
        A.renderGit();
        return;
      }
      state.status = st;
      const [log, branches, user] = await Promise.all([
        A.api("/api/git/log"), A.api("/api/git/branches"), A.api("/api/git/user"),
      ]);
      state.log = log.commits || [];
      state.branches = branches.branches || [];
      state.user = user.user;
      A.renderGit();
    } catch (e) {
      A.$("#git-panel").innerHTML = `<div class="empty-state"><div>${A.esc(e.message)}</div></div>`;
    }
  };

  A.renderGit = function () {
    const host = A.$("#git-panel");
    if (!host) return;
    A.$("#view-title").textContent = "Git";
    if (!state.status) {
      host.innerHTML = `<div class="empty-state">
        <div class="empty-icon">⑂</div>
        <div>当前工作区不是 Git 仓库</div>
        <button class="primary-btn" id="git-init" style="margin-top:8px">初始化仓库</button>
      </div>`;
      const btn = A.$("#git-init");
      if (btn) btn.onclick = async () => {
        try {
          await A.api("/api/git/init", { method: "POST", body: {} });
          A.toast("已初始化 Git 仓库", "ok");
          A.loadGit();
        } catch (e) { A.toast(e.message, "err"); }
      };
      return;
    }
    const st = state.status;
    const staged = st.changes.filter((c) => c.staged);
    const unstaged = st.changes.filter((c) => !c.staged);
    host.innerHTML = `
      <div class="git-left">
        <div class="git-head">
          <span class="branch-pill">${A.esc(st.branch || "detached")}</span>
          <select id="git-branch" class="model-select" style="max-width:150px">
            ${state.branches.map((b) => `<option value="${A.esc(b.name)}" ${b.current ? "selected" : ""}>${A.esc(b.name)}</option>`).join("")}
          </select>
          <span class="spacer" style="flex:1"></span>
          <button class="icon-btn" id="git-refresh" title="刷新">${A.icon("refresh")}</button>
        </div>
        <div class="git-scroll">
          <div class="git-section">暂存的更改 (${staged.length})</div>
          ${staged.map((c) => row(c, true)).join("") || `<div class="muted" style="padding:2px 10px;font-size:11.5px">无</div>`}
          <div class="git-section">更改 (${unstaged.length})</div>
          ${unstaged.map((c) => row(c, false)).join("") || `<div class="muted" style="padding:2px 10px;font-size:11.5px">工作区干净</div>`}
        </div>
        <div class="commit-box">
          <textarea id="commit-msg" placeholder="提交信息（⌘Enter 提交）"></textarea>
          <div class="row">
            <span class="muted" style="font-size:11px">${state.user && state.user.name ? A.esc(state.user.name) : "未配置 git 用户"}</span>
            <button class="primary-btn" id="do-commit" ${st.changes.length ? "" : "disabled"}>提交</button>
          </div>
        </div>
      </div>
      <div class="git-right">
        <div class="pane-head"><span id="diff-title">${state.selected ? A.esc(state.selected) : "提交历史"}</span>
          <div class="pane-actions"><button class="ghost-btn" id="git-log-tab">历史</button></div></div>
        <div style="max-height:36%;overflow:auto">
          ${state.log.map((c) => `<div class="log-item" data-hash="${c.hash}">
            <span class="h">${c.short}</span><div><div class="s">${A.esc(c.subject)}</div>
            <div class="m">${A.esc(c.author)} · ${A.esc(c.date)} ${c.refs ? "· " + A.esc(c.refs) : ""}</div></div></div>`).join("") || `<div class="empty-state"><div>没有提交</div></div>`}
        </div>
        <div class="diff-view" id="git-diff">${diffHtml(state.diff)}</div>
      </div>`;

    A.$("#git-refresh").onclick = () => A.loadGit();
    A.$("#do-commit").onclick = doCommit;
    const msg = A.$("#commit-msg");
    msg.onkeydown = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") doCommit(); };
    A.$("#git-branch").onchange = async (e) => {
      try {
        const r = await A.api("/api/git/checkout", { method: "POST", body: { ref: e.target.value } });
        if (!r.ok) throw new Error(r.err || "切换分支失败");
        A.toast("已切换到 " + e.target.value, "ok");
        A.loadGit();
        A.loadTree();
      } catch (err) { A.toast(err.message, "err"); }
    };
    A.$("#git-log-tab").onclick = () => {
      state.diff = "";
      state.selected = null;
      A.$("#diff-title").textContent = "提交历史";
      A.$("#git-diff").innerHTML = `<div class="empty-state"><div>点击左侧提交查看差异</div></div>`;
    };

    A.$$(".change-row", host).forEach((el) => {
      const path = el.dataset.path;
      el.onclick = async (e) => {
        if (e.target.dataset.op) return;
        state.selected = path;
        try {
          const d = await A.api("/api/git/diff?path=" + encodeURIComponent(path) + "&staged=" + (el.dataset.staged === "1" ? 1 : 0));
          state.diff = d.diff;
          A.$("#diff-title").textContent = path;
          A.$("#git-diff").innerHTML = diffHtml(d.diff);
        } catch (err) { A.toast(err.message, "err"); }
      };
      const ops = el.querySelectorAll(".op");
      ops.forEach((btn) => {
        btn.onclick = async (e) => {
          e.stopPropagation();
          const op = btn.dataset.op;
          try {
            if (op === "stage") await A.api("/api/git/stage", { method: "POST", body: { paths: [path] } });
            if (op === "unstage") await A.api("/api/git/unstage", { method: "POST", body: { paths: [path] } });
            if (op === "discard") {
              const ok = await A.confirm("丢弃更改", `<p>确定丢弃 <span class="mono">${A.esc(path)}</span> 的未暂存修改？</p>`);
              if (!ok) return;
              const r = await A.api("/api/git/discard", { method: "POST", body: { paths: [path] } });
              if (!r.ok) throw new Error(r.err);
            }
            A.loadGit();
          } catch (err) { A.toast(err.message, "err"); }
        };
      });
    });
    A.$$(".log-item", host).forEach((el) => {
      el.onclick = async () => {
        try {
          const d = await A.api("/api/git/diff?commit=" + el.dataset.hash);
          state.diff = d.diff;
          A.$("#diff-title").textContent = "提交 " + el.dataset.hash.slice(0, 8);
          A.$("#git-diff").innerHTML = diffHtml(d.diff);
        } catch (err) { A.toast(err.message, "err"); }
      };
    });
    if (state.diff) A.$("#git-diff").innerHTML = diffHtml(state.diff);
  };

  function row(c, staged) {
    return `<div class="change-row" data-path="${A.esc(c.path)}" data-staged="${staged ? 1 : 0}">
      <span class="status ${statusClass(c.status)}">${A.esc((c.status || "?")[0])}</span>
      <span class="p" title="${A.esc(c.path)}">${A.esc(c.path)}</span>
      ${staged
        ? `<button class="op" data-op="unstage">取消暂存</button>`
        : `<button class="op" data-op="stage">暂存</button>${c.untracked ? "" : `<button class="op" data-op="discard">丢弃</button>`}`}
    </div>`;
  }

  async function doCommit() {
    const msg = A.$("#commit-msg");
    if (!msg || !msg.value.trim()) return A.toast("请填写提交信息", "err");
    try {
      const r = await A.api("/api/git/commit", { method: "POST", body: { message: msg.value.trim() } });
      if (!r.ok) throw new Error(r.err || "提交失败");
      A.toast("提交成功", "ok");
      msg.value = "";
      state.diff = "";
      A.loadGit();
    } catch (e) { A.toast(e.message, "err"); }
  }

  window.renderGit = A.loadGit;
})();
