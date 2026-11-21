"""文件检查点：Agent 修改文件前自动快照，可一键回滚。"""
import json
import shutil
import time
import uuid
from pathlib import Path

import fsops
import store


def _dir(sid: str, cid: str) -> Path:
    d = store.CHECKPOINTS / sid / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def create(sid: str, label: str = "") -> dict:
    cid = uuid.uuid4().hex[:10]
    meta = {"id": cid, "ts": int(time.time() * 1000), "label": label, "files": []}
    _dir(sid, cid).joinpath("meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    return meta


def snapshot(sid: str, cid: str, root: str, rel: str):
    """在修改前保存文件快照（同一检查点内只保存一次）。"""
    meta_path = _dir(sid, cid) / "meta.json"
    try:
        meta = json.loads(meta_path.read_text("utf-8"))
    except Exception:
        meta = create(sid, "自动检查点")
        cid = meta["id"]
        meta_path = _dir(sid, cid) / "meta.json"
    for f in meta["files"]:
        if f["rel"] == rel:
            return
    p = fsops.resolve(root, rel)
    existed = p.exists()
    rec = {"rel": rel, "existed": existed}
    if existed:
        dst = _dir(sid, cid) / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        rec["size"] = p.stat().st_size
    meta["files"].append(rec)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")


def list_checkpoints(sid: str):
    base = store.CHECKPOINTS / sid
    out = []
    if base.exists():
        for d in base.iterdir():
            mp = d / "meta.json"
            if mp.exists():
                try:
                    m = json.loads(mp.read_text("utf-8"))
                    m["files"] = [f["rel"] for f in m.get("files", [])]
                    out.append(m)
                except Exception:
                    continue
    out.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return out


def restore(sid: str, cid: str, root: str):
    d = _dir(sid, cid)
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    restored = []
    for f in meta.get("files", []):
        target = fsops.resolve(root, f["rel"])
        if f.get("existed"):
            src = d / "files" / f["rel"]
            if src.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                restored.append(f["rel"])
        else:
            if target.exists() and target.is_file():
                target.unlink()
                restored.append(f["rel"] + " (删除)")
    return restored


def latest(sid: str):
    items = list_checkpoints(sid)
    return items[0] if items else None


def prune(sid: str, keep: int = 30):
    base = store.CHECKPOINTS / sid
    if not base.exists():
        return
    dirs = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)
