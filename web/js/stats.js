/* Token 与费用统计 */
(function () {
  const A = window.A;

  A.loadStats = async function () {
    const host = A.$("#stats-panel");
    if (!host) return;
    A.$("#view-title").textContent = "统计";
    try {
      const data = await A.api("/api/stats");
      const rows = data.rows || [];
      const total = rows.reduce((a, r) => {
        a.calls += 1; a.input += r.input || 0; a.output += r.output || 0; a.cost += r.cost || 0;
        return a;
      }, { calls: 0, input: 0, output: 0, cost: 0 });
      const byModel = {};
      rows.forEach((r) => {
        const key = (r.provider || "-") + " / " + (r.model || "-");
        const m = byModel[key] || (byModel[key] = { calls: 0, input: 0, output: 0, cost: 0, model: r.model, provider: r.provider });
        m.calls += 1; m.input += r.input || 0; m.output += r.output || 0; m.cost += r.cost || 0;
      });
      const models = Object.values(byModel).sort((a, b) => b.cost - a.cost);
      const recent = rows.slice(-40).reverse();
      host.innerHTML = `
        <div class="section-title">用量总览</div>
        <div class="section-desc">按渠道与模型统计调用次数、Token 与估算费用（单价来自模型配置）。</div>
        <div class="stat-cards">
          <div class="stat-card"><div class="k">调用次数</div><div class="v">${A.fmtNum(total.calls)}</div></div>
          <div class="stat-card"><div class="k">输入 Token</div><div class="v">${A.fmtNum(total.input)}</div></div>
          <div class="stat-card"><div class="k">输出 Token</div><div class="v">${A.fmtNum(total.output)}</div></div>
          <div class="stat-card"><div class="k">预估费用</div><div class="v">${A.fmtMoney(total.cost)}</div></div>
        </div>
        <div class="panel">
          <div class="panel-title">按模型</div>
          <table class="data"><thead><tr><th>供应商</th><th>模型</th><th>调用</th><th>输入</th><th>输出</th><th>费用</th></tr></thead><tbody>
          ${models.map((m) => `<tr><td>${A.esc(m.provider)}</td><td>${A.esc(m.model)}</td><td>${m.calls}</td>
            <td>${A.fmtNum(m.input)}</td><td>${A.fmtNum(m.output)}</td><td>${A.fmtMoney(m.cost)}</td></tr>`).join("")
            || `<tr><td colspan="6" class="muted">暂无数据</td></tr>`}
          </tbody></table>
        </div>
        <div class="panel">
          <div class="panel-title">最近调用</div>
          <table class="data"><thead><tr><th>时间</th><th>供应商</th><th>模型</th><th>输入</th><th>输出</th><th>费用</th></tr></thead><tbody>
          ${recent.map((r) => `<tr><td>${A.fmtTime(r.ts)}</td><td>${A.esc(r.provider || "")}</td><td>${A.esc(r.model || "")}</td>
            <td>${A.fmtNum(r.input)}</td><td>${A.fmtNum(r.output)}</td><td>${A.fmtMoney(r.cost)}</td></tr>`).join("")
            || `<tr><td colspan="6" class="muted">暂无数据</td></tr>`}
          </tbody></table>
        </div>`;
    } catch (e) {
      host.innerHTML = `<div class="empty-state"><div>${A.esc(e.message)}</div></div>`;
    }
  };
})();
