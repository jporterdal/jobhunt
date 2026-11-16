"""One ollmcp session in a pseudo-terminal, for the MCP measurement's session batches (`batch.py` runs it; see
docs/mcp-eval.md).

    session.py LOG_PREFIX QUESTIONS_FILE OLLMCP_COMMAND...

Types each question of QUESTIONS_FILE (one a line) once the client shows its prompt, answers each tool confirmation
with `y`, aborts a question at the client's loop limit, and records the terminal to LOG_PREFIX.raw and the TCP
connections of the client's process tree (it and the `jobhunt mcp` it starts) to LOG_PREFIX.conns.json. Prints
`question done=<True|False> <seconds>s: <question>` per question. Standard library only (Linux: /proc and `ss`).
The guards (demo database, loopback addresses) are batch.py's; run sessions through it.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time

PROMPT = "tools❯ ".encode()
CONFIRM = b"What would you like to do?"
LOOP = b"Loop Limit Reached"


class Session:
    def __init__(self, log_path: str, command: list[str]):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.update(COLUMNS="200", LINES="60", TERM="xterm-256color")
            os.execvp(command[0], command)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 200, 0, 0))
        self.raw = open(log_path + ".raw", "wb")  # noqa: SIM115 (open for the whole session)
        self.buf = b""
        self.conns: dict[tuple, str] = {}

    def tree(self) -> set[int]:
        pids, todo = {self.pid}, [self.pid]
        while todo:
            p = todo.pop()
            try:
                for t in os.listdir(f"/proc/{p}/task"):
                    with open(f"/proc/{p}/task/{t}/children") as children:
                        for c in children.read().split():
                            if int(c) not in pids:
                                pids.add(int(c))
                                todo.append(int(c))
            except OSError:
                pass
        return pids

    def note_connections(self) -> None:
        pids = self.tree()
        out = subprocess.run(["ss", "-tnpH"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            found = {int(p) for p in re.findall(r"pid=(\d+)", line)}
            if found & pids:
                f = line.split()
                name = re.search(r'\("([^"]+)"', line)
                key = (f[3], f[4], name.group(1) if name else "?")
                self.conns.setdefault(key, time.strftime("%H:%M:%S"))

    def pump(self, timeout: float):
        self.note_connections()
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return False
        try:
            data = os.read(self.fd, 65536)
        except OSError:
            return None
        self.raw.write(data)
        self.raw.flush()
        self.buf += data
        return True

    def wait(self, cond, limit: float, idle: float = 2.0, confirm: bool = False, mark: int = 0) -> bool:
        start = last = time.time()
        answered = 0
        while time.time() - start < limit:
            got = self.pump(0.5)
            if got is None:
                return False
            if got:
                last = time.time()
            if confirm:
                asks = self.buf[mark:].count(CONFIRM)
                if asks > answered and time.time() - last > 1.0:
                    answered = asks
                    self.send("y")
                    continue
                if LOOP in self.buf[mark:]:
                    print("loop limit reached", flush=True)
                    self.send("a")
                    mark = len(self.buf)
            if cond(self.buf) and time.time() - last > idle:
                return True
        return False

    def send(self, text: str) -> None:
        for ch in text:
            os.write(self.fd, ch.encode())
            time.sleep(0.01)
        time.sleep(0.2)
        os.write(self.fd, b"\r")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    log_path, questions_path, *command = argv
    with open(questions_path, encoding="utf-8") as f:
        questions = [q for q in f.read().splitlines() if q.strip()]
    s = Session(log_path, command)
    print("start", s.wait(lambda b: PROMPT in b, 180, idle=3), flush=True)
    s.send("/tools")
    s.wait(lambda b: b"> " in b, 30, idle=3)
    s.send("q")
    print("tools", s.wait(lambda b: PROMPT in b, 30, idle=3), flush=True)
    for q in questions:
        s.send(q)
        t0 = time.time()
        time.sleep(3)
        s.pump(0.5)
        mark = len(s.buf)
        ok = s.wait(lambda b, m=mark: PROMPT in b[m:], 900, idle=4, confirm=True, mark=mark)
        print(f"question done={ok} {time.time() - t0:.0f}s: {q}", flush=True)
    s.send("/quit")
    s.wait(lambda b: False, 10)
    if os.path.exists(f"/proc/{s.pid}"):
        os.kill(s.pid, 15)
    with open(log_path + ".conns.json", "w") as f:
        json.dump([list(k) + [v] for k, v in s.conns.items()], f, indent=1)
    print("connections:", *[f"{k} first {v}" for k, v in s.conns.items()], sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
