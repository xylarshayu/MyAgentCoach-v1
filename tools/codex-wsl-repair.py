#!/usr/bin/env python3
"""Narrow repairs for Codex Desktop 26.901.4073 + WSL. Dry-run by default.

Uses Codex's own app-server API; never edits SQLite or conversation contents.
Project cache repair requires the desktop app to be fully closed.
"""
import argparse
import copy
import csv
import hashlib
import json
import io
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid


MAPPING = "app-server-project-id-by-legacy-project-id-by-host"


def desktop_servers():
    found = []
    for entry in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = entry.read_bytes().split(b"\0")
            if b"app-server" in args and b"features.code_mode_host=true" in args:
                found.append(entry.parent.name)
        except OSError:
            pass
    return found


def require_desktop_closed():
    if desktop_servers():
        raise RuntimeError("Fully quit Codex Desktop before applying project repairs.")
    # Also check the Windows GUI: the backend can stop while the GUI still owns the cache.
    check = subprocess.run(
        ["/mnt/c/Windows/System32/tasklist.exe", "/FO", "CSV", "/NH"],
        capture_output=True, timeout=15, check=True,
    )
    images = {row[0].lower() for row in csv.reader(io.StringIO(check.stdout.decode(errors="replace"))) if row}
    if images.intersection({"codex.exe", "chatgpt.exe"}):
        raise RuntimeError("The Codex/ChatGPT desktop app is still running. Fully quit it before applying project repairs.")


def wait_for_desktop_exit(timeout):
    print("Waiting for Codex Desktop to close. Fully quit it; this terminal will perform the repair automatically.", flush=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            require_desktop_closed()
            return
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for Codex Desktop to close. No project repair was applied.")
            time.sleep(3)


class Server:
    def __init__(self, binary, home, sqlite_home):
        self.binary, self.home, self.sqlite_home = binary, home, sqlite_home

    def __enter__(self):
        env = dict(os.environ, CODEX_HOME=str(self.home), CODEX_SQLITE_HOME=str(self.sqlite_home))
        self.proc = subprocess.Popen(
            [str(self.binary), "app-server", "--listen", "stdio://"], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
        self.messages = queue.Queue()
        self.counter = 0
        def read():
            try:
                for line in self.proc.stdout:
                    self.messages.put(json.loads(line))
            except Exception as exc:
                self.messages.put(exc)
            finally:
                self.messages.put(EOFError("app-server closed its output"))
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            self.info = self.call("initialize", {
                "clientInfo": {"name": "codex_wsl_repair", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            })
            self.proc.stdin.write('{"method":"initialized"}\n')
            self.proc.stdin.flush()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def call(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.proc.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + 45
        while True:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if isinstance(message, Exception):
                raise message
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(message["error"].get("message", "app-server error"))
                return message["result"]
            if time.monotonic() >= deadline:
                raise TimeoutError(method)

    def __exit__(self, *_):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.reader.join(timeout=2)
        self.proc.stdout.close()


def linux_path(value, distro):
    if value.startswith("/"):
        return str(Path(value).resolve())
    parts = value.replace("\\", "/").split("/")
    if len(parts) >= 5 and parts[:2] == ["", ""] and parts[2].lower() in ("wsl$", "wsl.localhost"):
        if parts[3].lower() != distro.lower():
            raise ValueError("A cached project belongs to another WSL distribution; refusing to guess.")
        return "/" + "/".join(parts[4:])
    raise ValueError("Expected an absolute Linux path or a WSL UNC path.")


def register_plan(state, name, root, distro):
    result = copy.deepcopy(state)
    projects = result.setdefault("local-projects", {})
    matching = [p for p in projects.values() if any(linux_path(r, distro) == root for r in p.get("rootPaths", []))]
    if len(matching) > 1:
        raise ValueError("Multiple cached projects contain this root; resolve the duplicate first.")
    if matching:
        target = matching[0]
        if target.get("name") != name:
            raise ValueError("This root already belongs to a differently named project; refusing to rename it.")
    else:
        key = "local-" + hashlib.sha256((distro + ":" + root).encode()).hexdigest()[:32]
        if key in projects:
            raise ValueError("Project identifier collision.")
        stamp = int(time.time() * 1000)
        target = {"id": key, "name": name, "rootPaths": ["\\\\wsl.localhost\\" + distro + root.replace("/", "\\")], "createdAt": stamp, "updatedAt": stamp}
        projects[key] = target
        result.setdefault("project-order", []).append(key)
    return result, target


def archive(args, binary, sqlite_home):
    with sqlite3.connect(f"file:{sqlite_home / 'state_5.sqlite'}?mode=ro", uri=True) as db:
        row = db.execute("SELECT rollout_path, archived FROM threads WHERE id=?", (args.thread_id,)).fetchone()
    if row is None:
        raise ValueError("Task not found in the desktop's WSL database.")
    rollout, archived = Path(row[0]), bool(row[1])
    if archived:
        print("Already archived.")
        return
    parents = [p for p in rollout.parents if p.name == "sessions"]
    if len(parents) != 1 or not rollout.is_file():
        raise ValueError("Cannot identify a valid owning sessions directory.")
    owner = parents[0].parent
    print(json.dumps({"threadId": args.thread_id, "owningHome": str(owner), "action": "archive", "apply": args.apply}))
    if args.apply:
        with Server(binary, owner, sqlite_home) as server:
            server.call("thread/archive", {"threadId": args.thread_id})
        with sqlite3.connect(f"file:{sqlite_home / 'state_5.sqlite'}?mode=ro", uri=True) as db:
            archived = db.execute("SELECT archived FROM threads WHERE id=?", (args.thread_id,)).fetchone()[0]
        if not archived:
            raise RuntimeError("Archive did not persist.")
        print("Archive verified.")


def register(args, binary, sqlite_home):
    state_path = args.desktop_home / ".codex-global-state.json"
    original = state_path.read_bytes()
    state = json.loads(original)
    distro = os.environ.get("WSL_DISTRO_NAME")
    if not distro:
        raise ValueError("Run this command in the target WSL distribution.")
    root = linux_path(args.path, distro)
    if not Path(root).is_dir():
        raise ValueError("Requested project folder does not exist.")
    updated, target = register_plan(state, args.name, root, distro)
    imports = []
    for project in updated["local-projects"].values():
        roots = [linux_path(r, distro) for r in project.get("rootPaths", [])]
        if not all(Path(r).is_dir() for r in roots):
            raise ValueError("An existing project folder is missing; refusing partial migration.")
        imports.append((project, roots))
    print(json.dumps({"project": target["name"], "root": root, "existingProjectsToPreserve": len(state.get("local-projects", {})), "coreImports": len(imports), "apply": args.apply}, indent=2))
    if not args.apply:
        print("Dry run only. Apply requires Codex Desktop to be fully closed.")
        return
    require_desktop_closed()
    backup = Path.home() / ".codex" / "repair-backups" / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(state_path, backup / state_path.name)
    os.chmod(backup / state_path.name, 0o600)
    with Server(binary, args.desktop_home, sqlite_home) as server:
        identity = "local:" + server.info["codexHome"]
        mapping = updated.setdefault(MAPPING, {}).setdefault(identity, {})
        for project, roots in imports:
            if project["id"] in mapping:
                continue
            appearance = state.get("project-appearances", {}).get(project["id"])
            metadata = {}
            if isinstance(appearance, dict):
                metadata = {"appearance.color": appearance["color"], "appearance.marker": json.dumps(appearance["marker"], separators=(",", ":"))}
            response = server.call("project/import", {"idempotencyKey": project["id"], "name": project["name"], "roots": [{"path": r} for r in roots], "metadata": metadata})
            mapping[project["id"]] = response["project"]["id"]
        for project, roots in imports:
            actual = server.call("project/read", {"projectId": mapping[project["id"]]})["project"]
            if actual["name"] != project["name"] or [r["path"] for r in actual["roots"]] != roots:
                raise RuntimeError("Core project readback differs from the plan; cache was not changed.")
    require_desktop_closed()
    if state_path.read_bytes() != original:
        raise RuntimeError("Desktop state changed during repair; refusing to overwrite it. Rerun after closing the app.")
    temporary = state_path.with_name(state_path.name + ".repair-" + uuid.uuid4().hex)
    try:
        with temporary.open("x") as stream:
            json.dump(updated, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state_path)
    finally:
        temporary.unlink(missing_ok=True)
    print("Project registered; existing project mappings preserved. Restart Codex Desktop to verify the sidebar.")
    print("Desktop-state backup:", backup / state_path.name)
    print("This repairs the requested project and migration; it does not patch the app's New Project dialog.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-home", type=Path, default=Path("/mnt/c/Users/ayush/.codex"))
    parser.add_argument("--binary", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("archive")
    a.add_argument("thread_id")
    a.add_argument("--apply", action="store_true")
    p = sub.add_parser("register-project")
    p.add_argument("--name", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--wait-for-desktop-exit", action="store_true", help="Wait up to 10 minutes for the desktop to close before reading or changing its cache.")
    args = parser.parse_args()
    binaries = list((args.desktop_home / "bin" / "wsl").glob("*/codex"))
    binary = args.binary or (max(binaries, key=lambda p: p.stat().st_mtime) if binaries else None)
    if binary is None or not binary.is_file():
        parser.error("Cannot locate the desktop's bundled Linux Codex binary; pass --binary.")
    sqlite_home = Path.home() / ".codex" / "sqlite"
    try:
        if getattr(args, "wait_for_desktop_exit", False):
            if not args.apply:
                parser.error("--wait-for-desktop-exit requires --apply")
            wait_for_desktop_exit(600)
        (archive if args.command == "archive" else register)(args, binary, sqlite_home)
    except (RuntimeError, ValueError, OSError, queue.Empty, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Repair stopped: {exc}\n")


if __name__ == "__main__":
    main()
