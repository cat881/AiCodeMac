"""PTY 终端会话管理。"""
import base64
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid


class TermSession:
    def __init__(self, cwd: str, shell: str = "/bin/zsh", title: str = "终端"):
        self.id = uuid.uuid4().hex[:10]
        self.title = title
        self.cwd = cwd
        self.lock = threading.Condition()
        self.buf = bytearray()
        self.closed = False
        self.created = time.time()
        self.master, slave = pty.openpty()
        env = dict(os.environ)
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": env.get("LANG", "en_US.UTF-8")})
        self.proc = subprocess.Popen(
            [shell, "-l"],
            stdin=slave, stdout=slave, stderr=slave,
            cwd=cwd, env=env, preexec_fn=os.setsid, close_fds=True,
        )
        os.close(slave)
        flags = fcntl.fcntl(self.master, fcntl.F_GETFL)
        fcntl.fcntl(self.master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.resize(120, 32)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while not self.closed:
            try:
                r, _, _ = select.select([self.master], [], [], 0.5)
                if not r:
                    if self.proc.poll() is not None:
                        break
                    continue
                chunk = os.read(self.master, 65536)
                if not chunk:
                    break
                with self.lock:
                    self.buf.extend(chunk)
                    if len(self.buf) > 4_000_000:
                        del self.buf[:1_000_000]
                    self.lock.notify_all()
            except OSError:
                break
        with self.lock:
            self.closed = True
            self.lock.notify_all()

    def read_from(self, offset: int, timeout: float = 20.0):
        with self.lock:
            if offset < 0:
                offset = 0
            if offset < len(self.buf):
                data = bytes(self.buf[offset:offset + 65536])
                return data, offset + len(data)
            if self.closed:
                return b"", offset
            self.lock.wait(timeout)
            if offset < len(self.buf):
                data = bytes(self.buf[offset:offset + 65536])
                return data, offset + len(data)
            return b"", offset

    def write(self, data: bytes):
        if self.closed:
            return
        try:
            os.write(self.master, data)
        except OSError:
            pass

    def input_text(self, text: str):
        self.write(text.encode("utf-8", "replace"))

    def resize(self, cols: int, rows: int):
        try:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", max(rows, 2), max(cols, 2), 0, 0))
        except OSError:
            pass

    def info(self):
        alive = self.proc.poll() is None and not self.closed
        return {"id": self.id, "title": self.title, "cwd": self.cwd, "alive": alive,
                "offset": len(self.buf), "created": self.created}

    def close(self):
        if self.closed:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGHUP)
        except OSError:
            pass
        try:
            self.proc.terminate()
        except OSError:
            pass
        self.closed = True
        with self.lock:
            self.lock.notify_all()


class TermManager:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def create(self, cwd: str, title: str = "终端", shell: str = None):
        shell = shell or os.environ.get("SHELL") or "/bin/zsh"
        s = TermSession(cwd, shell, title)
        with self.lock:
            self.sessions[s.id] = s
        return s

    def get(self, sid: str):
        with self.lock:
            return self.sessions.get(sid)

    def close(self, sid: str):
        s = self.get(sid)
        if s:
            s.close()
            with self.lock:
                self.sessions.pop(sid, None)

    def list(self):
        with self.lock:
            return [s.info() for s in self.sessions.values()]
