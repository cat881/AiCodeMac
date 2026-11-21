/* CodeMirror 语言模式按需加载 */
(function () {
  const FILES = {
    javascript: "javascript.js", jsx: "jsx.js", xml: "xml.js", css: "css.js",
    htmlmixed: "htmlmixed.js", markdown: "markdown.js", python: "python.js",
    shell: "shell.js", clike: "clike.js", sql: "sql.js", yaml: "yaml.js",
    go: "go.js", rust: "rust.js", dockerfile: "dockerfile.js", diff: "diff.js",
    properties: "properties.js", toml: "toml.js", swift: "swift.js", java: "clike.js",
    php: "php.js", ruby: "ruby.js", lua: "lua.js", perl: "perl.js",
    powershell: "powershell.js", cmake: "cmake.js", nginx: "nginx.js", sass: "sass.js",
  };
  const DEPS = {
    htmlmixed: ["xml", "javascript", "css"],
    jsx: ["javascript"],
    sass: ["css"],
  };
  window.ensureCMMode = function (lang) {
    if (!lang || lang === "null" || lang === "text") return Promise.resolve();
    const file = FILES[lang] || null;
    if (!file) return Promise.resolve();
    const loadOne = (name) => {
      const f = FILES[name];
      if (!f || window.A.state.loadedModes[name]) return Promise.resolve();
      return new Promise((resolve) => {
        const s = document.createElement("script");
        s.src = "/vendor/mode/" + f;
        s.onload = () => { window.A.state.loadedModes[name] = true; resolve(); };
        s.onerror = () => resolve();
        document.head.appendChild(s);
      });
    };
    return Promise.all((DEPS[lang] || []).map(loadOne)).then(() => loadOne(lang));
  };
})();
