/* 设置面板 */
(function () {
  const A = window.A;
  let D = null;
  let section = "general";

  const TOOLS = [
    ["run_shell", "执行 Shell 命令"],
    ["write_file", "写入文件"],
    ["edit_file", "修改文件"],
    ["open_terminal", "打开终端"],
    ["mcp_call", "MCP 工具调用"],
    ["web_fetch", "抓取网页"],
  ];

  A.openSettings = function (sec) {
    section = sec || "general";
    D = JSON.parse(JSON.stringify(A.state.config));
    A.openModal("settings-modal");
    render();
  };

  function render() {
    const body = A.$("#settings-body");
    body.innerHTML = `
      <div class="settings-nav">
        ${nav("general", "常规")}
        ${nav("workspace", "工作区")}
        ${nav("providers", "AI 供应商")}
        ${nav("model", "模型与上下文")}
        ${nav("permissions", "权限与提示词")}
        ${nav("mcp", "MCP")}
        ${nav("data", "备份与关于")}
      </div>
      <div class="settings-content" id="settings-content"></div>`;
    A.$$(".settings-nav button", body).forEach((b) => {
      b.onclick = () => { section = b.dataset.sec; render(); };
    });
    const host = A.$("#settings-content");
    if (section === "general") renderGeneral(host);
    if (section === "workspace") renderWorkspace(host);
    if (section === "providers") renderProviders(host);
    if (section === "model") renderModel(host);
    if (section === "permissions") renderPermissions(host);
    if (section === "mcp") renderMcp(host);
    if (section === "data") renderData(host);
  }

  function nav(id, label) {
    return `<button data-sec="${id}" class="${section === id ? "active" : ""}">${label}</button>`;
  }

  function saveBtn(host, label) {
    const wrap = document.createElement("div");
    wrap.style.marginTop = "18px";
    wrap.innerHTML = `<button class="primary-btn">${label || "保存"}</button>`;
    wrap.querySelector("button").onclick = () => saveAll();
    host.appendChild(wrap);
  }

  async function saveAll() {
    try {
      await A.saveConfig(D);
      A.toast("设置已保存", "ok");
      if (A.state.view === "files") A.loadTree();
      if (A.state.view === "git") A.loadGit();
      A.renderSessions();
      A.renderChat();
      render();
    } catch (e) {
      A.toast(e.message, "err");
    }
  }

  // ---------------------------------------------------------------- 常规
  function renderGeneral(host) {
    host.innerHTML = `
      <div class="section-title">外观与语言</div>
      <div class="section-desc">主题、强调色与界面语言会立即生效。</div>
      <div class="row-2">
        <div class="field"><label>界面语言</label>
          <select id="s-lang"><option value="zh">简体中文</option><option value="en">English</option></select></div>
        <div class="field"><label>主题</label>
          <select id="s-theme"><option value="dark">深色</option><option value="light">浅色</option></select></div>
      </div>
      <div class="row-2">
        <div class="field"><label>强调色</label><input type="color" id="s-accent" style="height:34px;padding:2px"></div>
        <div class="field"><label>正文尺寸（px）</label><input type="number" id="s-font" min="12" max="18"></div>
      </div>
      <div class="field"><label>默认运行模式</label>
        <select id="s-mode">
          <option value="build">BUILD — 写操作需授权</option>
          <option value="plan">PLAN — 只读规划</option>
          <option value="auto">AUTO — 全自动</option>
        </select></div>`;
    A.$("#s-lang").value = D.language || "zh";
    A.$("#s-theme").value = D.theme || "dark";
    A.$("#s-accent").value = D.accent || "#4f8cff";
    A.$("#s-font").value = D.fontSize || 14;
    A.$("#s-mode").value = D.mode || "build";
    A.$("#s-lang").onchange = (e) => { D.language = e.target.value; A.state.config.language = e.target.value; A.applyStaticI18n(); A.renderSessions(); render(); };
    A.$("#s-theme").onchange = (e) => { D.theme = e.target.value; A.state.config.theme = e.target.value; A.applyTheme(); };
    A.$("#s-accent").oninput = (e) => { D.accent = e.target.value; A.state.config.accent = e.target.value; A.applyTheme(); };
    A.$("#s-font").onchange = (e) => { D.fontSize = Number(e.target.value); A.state.config.fontSize = D.fontSize; A.applyTheme(); };
    A.$("#s-mode").onchange = (e) => { D.mode = e.target.value; A.setMode(e.target.value); };
    saveBtn(host);
  }

  // ---------------------------------------------------------------- 工作区
  function renderWorkspace(host) {
    host.innerHTML = `
      <div class="section-title">工作区</div>
      <div class="section-desc">Agent 的读写、终端与 Git 操作都限制在此目录内。</div>
      <div class="field"><label>目录路径</label>
        <div class="split-actions">
          <input type="text" id="s-ws" style="flex:1" value="${A.esc(D.workspace || "")}">
          <button class="ghost-btn" id="s-ws-pick">选择…</button>
        </div>
        <div class="desc">切换后文件树、Git 与新建终端都会使用新目录；已有会话保留原工作区。</div>
      </div>
      <div class="field"><label>最近使用</label><div id="s-recent"></div></div>`;
    const recent = A.$("#s-recent");
    (D.recentWorkspaces || []).forEach((w) => {
      const row = A.h(`<div class="tree-row"><span class="fname mono">${A.esc(w)}</span></div>`);
      row.onclick = () => { A.$("#s-ws").value = w; };
      recent.appendChild(row);
    });
    A.$("#s-ws-pick").onclick = async () => {
      try {
        const r = await A.api("/api/workspace", { method: "POST", body: { path: "__pick__" } });
        if (r.workspace) {
          A.$("#s-ws").value = r.workspace;
          D.workspace = r.workspace;
          A.toast("工作区已切换", "ok");
          A.afterWorkspaceChange(r.workspace);
        }
      } catch (e) { A.toast(e.message, "err"); }
    };
    saveBtn(host, "保存工作区");
    const btn = host.querySelector(".primary-btn");
    btn.onclick = async () => {
      try {
        const r = await A.api("/api/workspace", { method: "POST", body: { path: A.$("#s-ws").value } });
        D.workspace = r.workspace;
        await saveAll();
        A.afterWorkspaceChange(r.workspace);
      } catch (e) { A.toast(e.message, "err"); }
    };
  }

  // ---------------------------------------------------------------- 供应商
  function renderProviders(host) {
    host.innerHTML = `
      <div class="section-title">AI 供应商</div>
      <div class="section-desc">支持 OpenAI / Anthropic / Gemini 协议与自定义端点。密钥仅保存在本机。</div>
      <div id="provider-list"></div>
      <div class="split-actions" style="margin-top:10px">
        <button class="ghost-btn" id="add-provider">＋ 添加自定义供应商</button>
        <button class="ghost-btn" id="add-preset">＋ 添加预设</button>
      </div>`;
    const list = A.$("#provider-list");
    (D.providers || []).forEach((p, idx) => list.appendChild(providerCard(p, idx)));
    A.$("#add-provider").onclick = () => {
      D.providers = D.providers || [];
      D.providers.push({
        id: "custom-" + Date.now().toString(36), name: "自定义供应商", protocol: "openai",
        baseUrl: "https://api.openai.com/v1", keys: [], models: [{ id: "", name: "", input: 0, output: 0 }],
      });
      render();
    };
    A.$("#add-preset").onclick = () => addPresetDialog();
    saveBtn(host, "保存供应商");
  }

  const PRESETS = [
    { name: "DeepSeek", protocol: "openai", baseUrl: "https://api.deepseek.com/v1", models: [{ id: "deepseek-chat", name: "DeepSeek Chat", input: 0.27, output: 1.1 }, { id: "deepseek-reasoner", name: "DeepSeek R1", input: 0.55, output: 2.19 }] },
    { name: "Moonshot", protocol: "openai", baseUrl: "https://api.moonshot.cn/v1", models: [{ id: "moonshot-v1-8k", name: "Moonshot 8K", input: 1.7, output: 1.7 }] },
    { name: "智谱 GLM", protocol: "openai", baseUrl: "https://open.bigmodel.cn/api/paas/v4", models: [{ id: "glm-4-plus", name: "GLM-4 Plus", input: 7, output: 7 }] },
    { name: "通义千问", protocol: "openai", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: [{ id: "qwen-max", name: "Qwen Max", input: 2.4, output: 9.6 }] },
    { name: "OpenRouter", protocol: "openai", baseUrl: "https://openrouter.ai/api/v1", models: [{ id: "anthropic/claude-sonnet-4", name: "Claude Sonnet 4", input: 3, output: 15 }] },
    { name: "SiliconFlow", protocol: "openai", baseUrl: "https://api.siliconflow.cn/v1", models: [{ id: "deepseek-ai/DeepSeek-V3", name: "DeepSeek V3", input: 0.27, output: 1.1 }] },
  ];

  function addPresetDialog() {
    const wrap = document.createElement("div");
    wrap.innerHTML = `<div class="approve-detail" style="max-height:none">
      ${PRESETS.map((p, i) => `<div><a href="#" data-i="${i}">${A.esc(p.name)}</a></div>`).join("")}
    </div>`;
    A.$("#settings-content").appendChild(wrap);
    wrap.querySelectorAll("a").forEach((a) => {
      a.onclick = (e) => {
        e.preventDefault();
        const p = PRESETS[Number(a.dataset.i)];
        D.providers = D.providers || [];
        D.providers.push({
          id: "preset-" + Date.now().toString(36), name: p.name, protocol: p.protocol,
          baseUrl: p.baseUrl, keys: [], models: p.models.map((m) => Object.assign({}, m)),
        });
        render();
      };
    });
  }

  function providerCard(p, idx) {
    const expanded = p._expanded !== false;
    const el = A.h(`<div class="provider-card">
      <div class="provider-head">
        <span class="pn">${A.esc(p.name || "未命名")}</span>
        <span class="pp">${A.esc(p.protocol)}</span>
        <span class="spacer"></span>
        <span class="badge ${p.hasKey || (p.keys || []).some((k) => k && !k.startsWith("••••")) ? "ok" : "no"}">
          ${p.hasKey || (p.keys || []).some((k) => k && !k.startsWith("••••")) ? "已配置密钥" : "未配置密钥"}</span>
        <span class="badge">${(p.models || []).length} 模型</span>
      </div>
      <div class="provider-body">
        <div class="row-2">
          <div class="field"><label>名称</label><input type="text" data-f="name" value="${A.esc(p.name || "")}"></div>
          <div class="field"><label>协议</label>
            <select data-f="protocol">
              <option value="openai">OpenAI 兼容</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Gemini</option>
            </select></div>
        </div>
        <div class="field"><label>Base URL</label><input type="text" data-f="baseUrl" value="${A.esc(p.baseUrl || "")}"></div>
        <div class="field"><label>API Keys（每行一个，支持多 Key 轮换）</label>
          <textarea data-f="keys" placeholder="sk-...">${A.esc((p.keys || []).join("\n"))}</textarea></div>
        <div class="field"><label>模型列表（单价：美元 / 百万 Token）</label>
          <table class="models-table"><thead><tr><th style="width:38%">模型 ID</th><th>显示名</th><th style="width:64px">输入</th><th style="width:64px">输出</th><th style="width:26px"></th></tr></thead>
          <tbody></tbody></table>
          <button class="ghost-btn" data-add-model>＋ 添加模型</button>
        </div>
        <div class="split-actions" style="margin-top:10px">
          <button class="ghost-btn" data-test>测试连接</button>
          <button class="ghost-btn" data-remove>删除供应商</button>
        </div>
      </div></div>`);
    const body = el.querySelector(".provider-body");
    if (!expanded) body.style.display = "none";
    el.querySelector(".provider-head").onclick = () => {
      p._expanded = body.style.display === "none";
      body.style.display = p._expanded ? "" : "none";
    };
    el.querySelector("[data-f=protocol]").value = p.protocol || "openai";
    el.querySelectorAll("[data-f]").forEach((inp) => {
      inp.oninput = () => {
        const f = inp.dataset.f;
        if (f === "keys") p.keys = inp.value.split("\n").map((s) => s.trim()).filter(Boolean);
        else p[f] = inp.value;
        el.querySelector(".pn").textContent = p.name || "未命名";
      };
    });
    const tbody = el.querySelector("tbody");
    const drawModels = () => {
      tbody.innerHTML = "";
      (p.models || []).forEach((m, mi) => {
        const tr = A.h(`<tr>
          <td><input data-mf="id" value="${A.esc(m.id || "")}" placeholder="model-id"></td>
          <td><input data-mf="name" value="${A.esc(m.name || "")}" placeholder="显示名"></td>
          <td><input data-mf="input" type="number" step="0.01" value="${m.input || 0}"></td>
          <td><input data-mf="output" type="number" step="0.01" value="${m.output || 0}"></td>
          <td><button class="rm">×</button></td></tr>`);
        tr.querySelectorAll("[data-mf]").forEach((inp) => {
          inp.oninput = () => {
            const f = inp.dataset.mf;
            m[f] = f === "input" || f === "output" ? Number(inp.value) : inp.value;
          };
        });
        tr.querySelector(".rm").onclick = () => { p.models.splice(mi, 1); drawModels(); };
        tbody.appendChild(tr);
      });
    };
    drawModels();
    el.querySelector("[data-add-model]").onclick = () => {
      p.models = p.models || [];
      p.models.push({ id: "", name: "", input: 0, output: 0 });
      drawModels();
    };
    el.querySelector("[data-remove]").onclick = async () => {
      const ok = await A.confirm("删除供应商", `<p>确定删除 <b>${A.esc(p.name)}</b>？其密钥与模型配置会一并移除。</p>`);
      if (!ok) return;
      D.providers.splice(idx, 1);
      render();
    };
    el.querySelector("[data-test]").onclick = async () => {
      try {
        await saveAll();
        const model = (p.models || [])[0];
        const r = await A.api("/api/provider/test", { method: "POST", body: { providerId: p.id, model: model && model.id } });
        A.toast(r.ok ? "连接成功：" + r.reply : "失败：" + r.error, r.ok ? "ok" : "err");
      } catch (e) { A.toast(e.message, "err"); }
    };
    return el;
  }

  // ---------------------------------------------------------------- 模型
  function renderModel(host) {
    const provs = D.providers || [];
    host.innerHTML = `
      <div class="section-title">模型与上下文</div>
      <div class="section-desc">选择默认模型，并配置上下文压缩与网络代理。</div>
      <div class="row-2">
        <div class="field"><label>供应商</label><select id="m-prov">${provs.map((p) => `<option value="${p.id}">${A.esc(p.name)}</option>`).join("")}</select></div>
        <div class="field"><label>模型</label><select id="m-model"></select></div>
      </div>
      <div class="row-2">
        <div class="field"><label>上下文上限（Token）</label><input type="number" id="m-limit" min="8000" step="1000"></div>
        <div class="field"><label>压缩触发比例</label><input type="number" id="m-ratio" min="0.3" max="0.9" step="0.05"></div>
      </div>
      <div class="row-2">
        <div class="field"><label>Key 轮换策略</label><select id="m-rot"><option value="sequential">顺序使用</option><option value="round_robin">轮询</option></select></div>
        <div class="field"><label>网络代理（可选）</label><input type="text" id="m-proxy" placeholder="http://127.0.0.1:7890"></div>
      </div>`;
    const provSel = A.$("#m-prov"), modelSel = A.$("#m-model");
    const fillModels = () => {
      const p = provs.find((x) => x.id === provSel.value);
      modelSel.innerHTML = ((p && p.models) || []).map((m) => `<option value="${m.id}">${A.esc(m.name || m.id)}</option>`).join("");
      if (D.active && D.active.providerId === provSel.value && D.active.model) modelSel.value = D.active.model;
    };
    provSel.value = (D.active && D.active.providerId) || (provs[0] && provs[0].id) || "";
    fillModels();
    provSel.onchange = () => { fillModels(); syncActive(); };
    modelSel.onchange = syncActive;
    function syncActive() {
      D.active = { providerId: provSel.value, model: modelSel.value };
      A.state.config.active = D.active;
      A.buildModelOptions();
      A.updateModeButtons();
    }
    syncActive();
    A.$("#m-limit").value = D.contextLimit || 128000;
    A.$("#m-ratio").value = D.compressRatio || 0.6;
    A.$("#m-rot").value = D.keyRotation || "sequential";
    A.$("#m-proxy").value = D.proxy || "";
    A.$("#m-limit").oninput = (e) => D.contextLimit = Number(e.target.value);
    A.$("#m-ratio").oninput = (e) => D.compressRatio = Number(e.target.value);
    A.$("#m-rot").onchange = (e) => D.keyRotation = e.target.value;
    A.$("#m-proxy").oninput = (e) => D.proxy = e.target.value;
    saveBtn(host);
  }

  // ---------------------------------------------------------------- 权限
  function renderPermissions(host) {
    host.innerHTML = `
      <div class="section-title">工具权限</div>
      <div class="section-desc">AUTO 模式跳过所有确认；PLAN 模式始终禁止写操作。</div>
      <div id="perm-list"></div>
      <div class="field" style="margin-top:14px"><label>已记住「始终允许」的工具</label>
        <div class="split-actions" id="always-list"></div></div>
      <div class="field"><label>系统提示词附加（App 升级不丢失）</label>
        <textarea id="s-sys" style="min-height:110px" placeholder="例如：本项目使用 TypeScript，测试命令为 pnpm test…"></textarea>
        <div class="desc">会追加在内置系统提示词之后，用于项目约定、代码风格与额外规则。</div></div>`;
    const list = A.$("#perm-list");
    TOOLS.forEach(([key, label]) => {
      const cur = (D.permissions && D.permissions[key]) || "ask";
      const row = A.h(`<div class="permission-row">
        <div class="pl">${label}<small>${key}</small></div>
        <select data-tool="${key}">
          <option value="allow">允许</option><option value="ask">询问</option><option value="deny">禁止</option>
        </select></div>`);
      row.querySelector("select").value = cur;
      row.querySelector("select").onchange = (e) => {
        D.permissions = D.permissions || {};
        D.permissions[key] = e.target.value;
      };
      list.appendChild(row);
    });
    const always = A.$("#always-list");
    if (!(D.alwaysAllow || []).length) always.innerHTML = `<span class="muted" style="font-size:12px">无</span>`;
    (D.alwaysAllow || []).forEach((tool) => {
      const chip = A.h(`<span class="badge">${A.esc(tool)} <a href="#" style="margin-left:4px">×</a></span>`);
      chip.querySelector("a").onclick = (e) => {
        e.preventDefault();
        D.alwaysAllow = D.alwaysAllow.filter((x) => x !== tool);
        saveAll().then(render);
      };
      always.appendChild(chip);
    });
    A.$("#s-sys").value = D.systemPrompt || "";
    A.$("#s-sys").oninput = (e) => D.systemPrompt = e.target.value;
    saveBtn(host);
  }

  // ---------------------------------------------------------------- MCP
  function renderMcp(host) {
    host.innerHTML = `
      <div class="section-title">MCP 服务器</div>
      <div class="section-desc">支持本地 stdio 与远程 HTTP 服务器，工具会自动加入 Agent 工具集。</div>
      <div class="field"><label>配置 JSON</label>
        <textarea id="mcp-json" spellcheck="false" style="min-height:190px;font-family:var(--mono);font-size:12px">{}</textarea>
        <div class="desc">示例：{"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/tmp"]}}</div>
      </div>
      <div class="split-actions"><button class="ghost-btn" id="mcp-reload">保存并重连</button></div>
      <div class="field" style="margin-top:16px"><label>连接状态</label><div id="mcp-status" class="muted" style="font-size:12px"></div></div>`;
    A.$("#mcp-json").value = JSON.stringify(D.mcpServers || {}, null, 2);
    const showStatus = async () => {
      try {
        const r = await A.api("/api/mcp/status");
        A.$("#mcp-status").innerHTML = (r.servers || []).map((s) => `<div>• ${A.esc(s.name)} — ${s.connected ? "已连接" : "失败" + (s.error ? "：" + A.esc(s.error) : "")}（${(s.tools || []).length} 个工具）</div>`).join("") || "尚未配置";
      } catch (e) {}
    };
    showStatus();
    A.$("#mcp-reload").onclick = async () => {
      try {
        D.mcpServers = JSON.parse(A.$("#mcp-json").value || "{}");
        await saveAll();
        await A.api("/api/mcp/reload", { method: "POST", body: {} });
        A.toast("MCP 已重连", "ok");
        showStatus();
      } catch (e) { A.toast("JSON 解析失败：" + e.message, "err"); }
    };
    saveBtn(host, "保存配置");
  }

  // ---------------------------------------------------------------- 数据
  function renderData(host) {
    host.innerHTML = `
      <div class="section-title">备份与还原</div>
      <div class="section-desc">导出内容包含供应商配置、密钥、会话与检查点索引；请妥善保管。</div>
      <div class="split-actions">
        <button class="ghost-btn" id="do-export">导出备份到「下载」</button>
        <button class="ghost-btn" id="do-import">导入备份…</button>
        <input type="file" id="import-file" accept="application/json" hidden>
      </div>
      <div class="section-title" style="margin-top:26px">关于</div>
      <div class="section-desc">AiCode for macOS · 复刻 jieapi/AiCode 的核心能力（AI Agent、终端、Git、文件编辑器、MCP）。</div>
      <div class="panel"><table class="data"><tbody>
        <tr><td style="width:140px">版本</td><td>${A.state.version || "1.0.0"}</td></tr>
        <tr><td>数据目录</td><td>~/Library/Application Support/AiCodeMac</td></tr>
        <tr><td>工作区</td><td>${A.esc(D.workspace || "")}</td></tr>
        <tr><td>技能目录</td><td class="muted">工作区/.aicode/skills · 数据目录/skills</td></tr>
        <tr><td>项目记忆</td><td class="muted">工作区 AGENTS.md / AICODE.md</td></tr>
      </tbody></table></div>`;
    A.$("#do-export").onclick = async () => {
      try {
        const r = await A.api("/api/backup/save", { method: "POST", body: {} });
        A.toast("已导出到 " + r.path, "ok");
      } catch (e) { A.toast(e.message, "err"); }
    };
    A.$("#do-import").onclick = () => A.$("#import-file").click();
    A.$("#import-file").onchange = async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      try {
        const text = await f.text();
        const data = JSON.parse(text);
        await A.api("/api/backup/import", { method: "POST", body: { data } });
        A.toast("导入完成，正在重新加载…", "ok");
        setTimeout(() => location.reload(), 800);
      } catch (err) { A.toast("导入失败：" + err.message, "err"); }
    };
  }
})();
