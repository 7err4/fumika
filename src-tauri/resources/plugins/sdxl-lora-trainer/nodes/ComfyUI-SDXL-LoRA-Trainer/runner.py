# -*- coding: utf-8 -*-
"""Detached runner (own console window): shows the output live AND writes it to a log the ComfyUI status node can read.
    runner.py one <log> <cwd> -- <cmd ...>      one command (training)
    runner.py steps <steps.json> <log>         several commands in a row (install), stops at the first failure"""
import json
import os
import subprocess
import sys
import threading


def run(cmd, cwd, log):
    log.write(("\n$ " + " ".join(cmd) + "\n").encode()); log.flush()
    # UTF-8 for the child: its stdout is a pipe, which Windows would encode in cp1252 - sd-scripts prints Japanese status lines
    # and died with UnicodeEncodeError (trainer test 22 Oct)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    except OSError as e:   # e.g. git not on PATH: the log must still end with an exit line, or the node waits for it forever
        log.write(f"could not start {cmd[0]}: {e}\n".encode()); log.flush()
        return 127
    while True:
        b = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(1)
        if not b:
            break
        sys.stdout.buffer.write(b); sys.stdout.flush(); log.write(b); log.flush()
    return p.wait()


def heartbeat(path, stop):
    """touch the log every minute: a quiet step (uv downloading torch prints nothing) still counts as running"""
    while not stop.wait(60):
        try:
            os.utime(path)
        except OSError:
            pass


def main():
    mode = sys.argv[1]
    logp = sys.argv[2] if mode == "one" else sys.argv[3]
    stop = threading.Event()
    with open(logp, "wb") as log:   # a new run starts a new log: an old TRAIN_EXIT 1 must not mark it failed
        threading.Thread(target=heartbeat, args=(logp, stop), daemon=True).start()
        if mode == "one":
            cwd, cmd = sys.argv[3], sys.argv[sys.argv.index("--") + 1:]
            rc = run(cmd, cwd, log); log.write(f"\nTRAIN_EXIT {rc}\n".encode())
        else:
            job = json.load(open(sys.argv[2], encoding="utf-8"))
            rc = 0
            for cmd in job["steps"]:
                rc = run(cmd, job["cwd"] if cmd[0] != "git" else None, log)
                if rc:
                    break
            log.write(f"\nINSTALL_EXIT {rc}\n".encode())
        stop.set()
    if rc and sys.stdin and sys.stdin.isatty():   # own console window (Windows); detached on Linux
        try:
            input("\nFailed - press Enter to close this window.")
        except EOFError:
            pass


if __name__ == "__main__":
    main()
