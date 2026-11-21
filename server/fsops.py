"""工作区文件操作（受限根目录）。"""
import fnmatch
import os
import re
from pathlib import Path

IGNORE_DIRS = {".git", "node_modules", "dist", "build", ".next", ".nuxt", ".venv", "venv",
               "__pycache__", ".idea", ".gradle", ".dart_tool", "Pods", "target", ".DS_Store",
               ".cache", "vendor", "coverage", ".mypy_cache", ".pytest_cache"}

EXT_LANG = {
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "jsx", ".ts": "javascript",
    ".tsx": "jsx", ".json": "javascript", ".html": "htmlmixed", ".htm": "htmlmixed", ".css": "css",
    ".scss": "sass", ".less": "css", ".md": "markdown", ".markdown": "markdown", ".py": "python",
    ".sh": "shell", ".zsh": "shell", ".bash": "shell", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
    ".sql": "sql", ".go": "go", ".rs": "rust", ".swift": "swift", ".java": "clike", ".kt": "clike",
    ".c": "clike", ".h": "clike", ".cpp": "clike", ".hpp": "clike", ".m": "clike", ".php": "php",
    ".rb": "ruby", ".lua": "lua", ".pl": "perl", ".ps1": "powershell", ".diff": "diff", ".patch": "diff",
    ".ini": "properties", ".conf": "nginx", ".xml": "xml", ".vue": "htmlmixed", ".svelte": "htmlmixed",
}


class FsError(Exception):
    pass


def resolve(root: str, rel: str) -> Path:
    rootp = Path(root).expanduser().resolve()
    if not rel or rel in (".", "./"):
        return rootp
    p = Path(rel).expanduser()
    full = p if p.is_absolute() else (rootp / p)
    full = full.resolve()
    try:
        full.relative_to(rootp)
    except ValueError:
        raise FsError("路径超出工作区: %s" % rel)
    return full


def rel_of(root: str, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(root).expanduser().resolve()))
    except ValueError:
        return str(path)


def tree(root: str, rel: str = ".", depth: int = 3):
    base = resolve(root, rel)
    if not base.is_dir():
        raise FsError("不是目录: %s" % rel)

    def walk(p: Path, d: int):
        items = []
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return items
        for e in entries:
            if e.name in IGNORE_DIRS or e.name.startswith(".") and e.name not in (".env", ".gitignore"):
                continue
            node = {"name": e.name, "path": rel_of(root, e), "dir": e.is_dir()}
            if e.is_dir() and d > 0:
                node["children"] = walk(e, d - 1)
            if e.is_file():
                try:
                    node["size"] = e.stat().st_size
                except OSError:
                    node["size"] = 0
                node["lang"] = EXT_LANG.get(e.suffix.lower(), "clike")
            items.append(node)
        return items

    return {"name": base.name or str(base), "path": rel_of(root, base), "dir": True, "children": walk(base, depth - 1)}


def read_text(root: str, rel: str, max_bytes: int = 2_000_000):
    p = resolve(root, rel)
    if p.is_dir():
        raise FsError("是目录: %s" % rel)
    if not p.exists():
        raise FsError("文件不存在: %s" % rel)
    raw = p.read_bytes()
    if b"\x00" in raw[:4096]:
        raise FsError("二进制文件，无法以文本打开")
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", "replace")
    return {"path": rel_of(root, p), "content": text, "truncated": truncated,
            "size": len(raw), "lang": EXT_LANG.get(p.suffix.lower(), "clike"),
            "mtime": int(p.stat().st_mtime * 1000)}


def write_text(root: str, rel: str, content: str):
    p = resolve(root, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".aicode.tmp")
    tmp.write_text(content, "utf-8")
    tmp.replace(p)
    return {"path": rel_of(root, p), "size": p.stat().st_size}


def mkdir(root: str, rel: str):
    p = resolve(root, rel)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": rel_of(root, p)}


def remove(root: str, rel: str):
    p = resolve(root, rel)
    if p == Path(root).expanduser().resolve():
        raise FsError("不能删除工作区根目录")
    if p.is_dir():
        import shutil
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    return {"ok": True}


def rename(root: str, src: str, dst: str):
    a, b = resolve(root, src), resolve(root, dst)
    b.parent.mkdir(parents=True, exist_ok=True)
    a.rename(b)
    return {"path": rel_of(root, b)}


def search(root: str, pattern: str, glob: str = "", max_results: int = 80, case_sensitive=False):
    base = Path(root).expanduser().resolve()
    try:
        rx = re.compile(pattern, 0 if case_sensitive else re.I)
    except re.error as e:
        raise FsError("正则无效: %s" % e)
    results = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            if glob and not fnmatch.fnmatch(fn, glob):
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > 1_500_000:
                    continue
                raw = p.read_bytes()
                if b"\x00" in raw[:2048]:
                    continue
                for i, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
                    if rx.search(line):
                        results.append({"path": rel_of(root, p), "line": i, "text": line.strip()[:300]})
                        if len(results) >= max_results:
                            return results
            except (OSError, PermissionError):
                continue
    return results


def find_files(root: str, pattern: str, max_results: int = 100):
    base = Path(root).expanduser().resolve()
    rx = re.compile(fnmatch.translate(pattern).replace(".*", ".*"), re.I)
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if rx.match(fn):
                out.append(rel_of(root, Path(dirpath) / fn))
                if len(out) >= max_results:
                    return out
    return out
