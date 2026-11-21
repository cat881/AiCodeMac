"""Git 集成。"""
import os
import subprocess
from pathlib import Path


def run_git(cwd: str, args, timeout=60, identity=None):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("LC_ALL", "en_US.UTF-8")
    cmd = ["git"]
    if identity and identity.get("name"):
        cmd += ["-c", "user.name=" + identity["name"]]
    if identity and identity.get("email"):
        cmd += ["-c", "user.email=" + identity["email"]]
    cmd += args
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, env=env)
        return {"code": p.returncode, "out": p.stdout.decode("utf-8", "replace"),
                "err": p.stderr.decode("utf-8", "replace")}
    except subprocess.TimeoutExpired:
        return {"code": 124, "out": "", "err": "git 命令超时"}
    except FileNotFoundError:
        return {"code": 127, "out": "", "err": "未找到 git"}
    except OSError as e:
        return {"code": 1, "out": "", "err": str(e)}


def is_repo(cwd: str) -> bool:
    r = run_git(cwd, ["rev-parse", "--is-inside-work-tree"])
    return r["code"] == 0 and r["out"].strip() == "true"


def status(cwd: str):
    if not is_repo(cwd):
        return {"repo": False, "changes": [], "branch": "", "ahead": 0, "behind": 0}
    st = run_git(cwd, ["status", "--porcelain=v1", "-z", "-b"])
    branch, ahead, behind = "", 0, 0
    changes = []
    parts = st["out"].split("\x00")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        if entry.startswith("##"):
            head = entry[2:].strip()
            branch = head.split("...")[0].strip()
            if "ahead " in head:
                try:
                    ahead = int(head.split("ahead ")[1].split("]")[0].split(",")[0])
                except Exception:
                    pass
            if "behind " in head:
                try:
                    behind = int(head.split("behind ")[1].split("]")[0].split(",")[0])
                except Exception:
                    pass
            continue
        if len(entry) < 3:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        orig = ""
        if x in ("R", "C") and i < len(parts):
            orig = parts[i]
            i += 1
        changes.append({
            "x": x, "y": y, "path": path, "orig": orig,
            "staged": x not in (" ", "?"),
            "untracked": x == "?",
            "status": (x + y).strip(),
        })
    return {"repo": True, "branch": branch, "ahead": ahead, "behind": behind, "changes": changes}


def log(cwd: str, limit=80):
    fmt = "%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%D"
    r = run_git(cwd, ["log", "--pretty=format:" + fmt, "--date=iso", "-n", str(limit)])
    if r["code"] != 0:
        return []
    out = []
    for line in r["out"].splitlines():
        f = line.split("\x1f")
        if len(f) >= 6:
            out.append({"hash": f[0], "short": f[1], "author": f[2], "date": f[3],
                        "subject": f[4], "refs": f[5]})
    return out


def diff(cwd: str, path: str = "", staged=False, commit=""):
    args = ["diff"]
    if commit:
        args += ["show", commit, "--format=fuller"]
        if path:
            args += ["--", path]
    else:
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
    r = run_git(cwd, args)
    return {"code": r["code"], "diff": r["out"], "err": r["err"]}


def stage(cwd: str, paths):
    return run_git(cwd, ["add", "--"] + list(paths))


def unstage(cwd: str, paths):
    return run_git(cwd, ["restore", "--staged", "--"] + list(paths))


def discard(cwd: str, paths):
    return run_git(cwd, ["restore", "--worktree", "--"] + list(paths))


def commit(cwd: str, message: str, identity=None):
    return run_git(cwd, ["commit", "-m", message], identity=identity)


def branches(cwd: str):
    r = run_git(cwd, ["branch", "-a", "-vv"])
    out = []
    for line in r["out"].splitlines():
        if not line.strip():
            continue
        cur = line.startswith("*")
        body = line[1:].strip() if cur else line.strip()
        parts = body.split(None, 2)
        out.append({"name": parts[0] if parts else "", "current": cur,
                    "head": parts[1] if len(parts) > 1 else "", "subject": parts[2] if len(parts) > 2 else ""})
    return out


def checkout(cwd: str, ref: str, create=False):
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(ref)
    return run_git(cwd, args)


def tags(cwd: str):
    r = run_git(cwd, ["tag", "--sort=-creatordate"])
    return [t for t in r["out"].splitlines() if t.strip()]


def current_user(cwd: str):
    name = run_git(cwd, ["config", "user.name"])["out"].strip()
    email = run_git(cwd, ["config", "user.email"])["out"].strip()
    return {"name": name, "email": email}
