/* Markdown 渲染、代码高亮与 文件:行号 链接 */
(function () {
  const A = window.A;
  if (window.marked) {
    marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
  }

  const FILE_RE = /((?:[\w.\-@/]+)\.(?:py|js|mjs|ts|tsx|jsx|kt|kts|java|swift|c|cc|h|hpp|cpp|go|rs|rb|php|css|scss|html|htm|json|md|yml|yaml|toml|sh|zsh|bash|xml|sql|gradle|txt|conf|ini|lua|vue|svelte)):(\d+)/g;

  function escapeHtml(s) {
    return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  A.renderMarkdown = function (text) {
    if (!text) return "";
    let html = "";
    try {
      html = marked.parse(text);
    } catch (e) {
      html = "<p>" + escapeHtml(text) + "</p>";
    }
    if (window.DOMPurify) {
      html = DOMPurify.sanitize(html, {
        ADD_ATTR: ["target"],
        FORBID_TAGS: ["style", "iframe", "form", "input", "button"],
      });
    }
    return html;
  };

  A.decorateMarkdown = function (root) {
    if (!root) return;
    root.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".copy-code")) return;
      const btn = document.createElement("button");
      btn.className = "copy-code";
      btn.textContent = "复制";
      btn.onclick = () => {
        const code = pre.querySelector("code");
        A.copy(code ? code.innerText : pre.innerText);
      };
      pre.appendChild(btn);
    });
    root.querySelectorAll("pre code").forEach((code) => {
      if (window.hljs && !code.dataset.hl) {
        try { hljs.highlightElement(code); code.dataset.hl = "1"; } catch (e) {}
      }
    });
    root.querySelectorAll("a").forEach((a) => {
      if (a.href && !a.href.startsWith("file:")) {
        a.target = "_blank";
        a.rel = "noreferrer";
      }
    });
    linkifyText(root);
  };

  function linkifyText(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const targets = [];
    let n;
    while ((n = walker.nextNode())) {
      const parent = n.parentElement;
      if (!parent) continue;
      const tag = parent.tagName;
      if (tag === "A" || tag === "CODE" || tag === "PRE" || tag === "SCRIPT" || tag === "STYLE") continue;
      if (!n.nodeValue || !FILE_RE.test(n.nodeValue)) continue;
      FILE_RE.lastIndex = 0;
      targets.push(n);
    }
    targets.forEach((node) => {
      const text = node.nodeValue;
      const frag = document.createDocumentFragment();
      let last = 0;
      let m;
      FILE_RE.lastIndex = 0;
      while ((m = FILE_RE.exec(text))) {
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        const a = document.createElement("a");
        a.className = "file-link";
        a.href = "#";
        a.dataset.path = m[1];
        a.dataset.line = m[2];
        a.textContent = m[0];
        a.style.textDecoration = "none";
        frag.appendChild(a);
        last = m.index + m[0].length;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(frag, node);
    });
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a.file-link");
    if (!a) return;
    e.preventDefault();
    if (window.A.openFile) window.A.openFile(a.dataset.path, parseInt(a.dataset.line || "1", 10));
  });
})();
