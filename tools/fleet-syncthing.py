#!/usr/bin/env python3
"""Small, explicit Syncthing bootstrap for the separate work configuration share.

Never copies credentials or modifies an existing personal folder. API keys are
read locally in memory, never accepted on argv or printed. Run --help first.
"""

import argparse
import hashlib
import io
import json
import os
import pathlib
import platform
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HOME = pathlib.Path.home()
VERSION = "2.1.6"
DIGEST = "524ef4e1df1850b719e2378c8369956f4e5f2ab9a46fdf7f45f2b925012147aa"
FOLDER = "xylar-work-config"


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def config_path():
    candidates = [HOME / "Library/Application Support/Syncthing/config.xml",
                  HOME / ".local/state/syncthing/config.xml",
                  HOME / ".config/syncthing/config.xml"]
    found = [p for p in candidates if p.is_file()]
    if len(found) != 1:
        raise RuntimeError("Expected exactly one existing native Syncthing config")
    return found[0]


class API:
    def __init__(self):
        self.path = config_path()
        root = ET.parse(self.path).getroot()
        address = root.findtext("gui/address")
        if address not in ("127.0.0.1:8384", "localhost:8384"):
            raise RuntimeError("Expected loopback management address on port 8384")
        self.base = "http://" + address
        self.key = root.findtext("gui/apikey")

    def call(self, path, data=None, method=None):
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(self.base + "/rest/" + path, data=body,
                                     method=method, headers={"X-API-Key": self.key,
                                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = response.read()
        return json.loads(payload) if payload else None

    def backup(self):
        parent = HOME / ".local/state/fleet-setup/backups"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest = parent / ("syncthing-config-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".xml")
        with dest.open("xb") as stream:
            os.chmod(dest, 0o600)
            stream.write(self.path.read_bytes())


def install():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Bootstrap is only for Linux x86_64; use native package management elsewhere")
    state = HOME / ".local/state/syncthing"
    unit = HOME / ".config/systemd/user/syncthing.service"
    link = HOME / ".local/bin/syncthing"
    if (shutil.which("syncthing") or state.exists() or unit.exists() or link.exists()
            or (HOME / ".config/syncthing").exists() or (HOME / "sync-plane").exists()):
        raise RuntimeError("Existing binary/config/service/share detected; refusing fresh bootstrap")
    if subprocess.run(["systemctl", "--user", "cat", "syncthing.service"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("Existing service definition detected")
    url = ("https://github.com/syncthing/syncthing/releases/download/v" + VERSION
           + "/syncthing-linux-amd64-v" + VERSION + ".tar.gz")
    with urllib.request.urlopen(url, timeout=45) as response:
        archive = response.read(32 * 1024 * 1024)
        if response.read(1):
            raise RuntimeError("Unexpectedly large release archive")
    if hashlib.sha256(archive).hexdigest() != DIGEST:
        raise RuntimeError("Official release digest mismatch")
    target = HOME / (".local/share/syncthing/v" + VERSION)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = target / "syncthing"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = tar.getmember("syncthing-linux-amd64-v" + VERSION + "/syncthing")
        if not member.isfile():
            raise RuntimeError("Release binary is not a regular member")
        data = tar.extractfile(member).read()
    with binary.open("xb") as stream:
        stream.write(data)
    binary.chmod(0o755)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(binary)
    run(str(binary), "generate", "--home", str(state), "--no-port-probing")
    config = state / "config.xml"
    tree = ET.parse(config)
    root = tree.getroot()
    for folder in root.findall("folder"):
        root.remove(folder)
    root.find("gui/address").text = "127.0.0.1:8384"
    root.find("options/startBrowser").text = "false"
    root.find("options/autoUpgradeIntervalH").text = "0"
    tree.write(config, encoding="utf-8", xml_declaration=True)
    config.chmod(0o600)
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]\nDescription=Syncthing user file synchronization\nAfter=network.target\n\n"
                    "[Service]\nExecStart=" + str(binary) + " serve --home=" + str(state)
                    + " --no-browser --no-restart --no-upgrade\nRestart=on-failure\nRestartSec=5\n"
                    "SuccessExitStatus=3 4\nUMask=0077\n\n[Install]\nWantedBy=default.target\n")
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "--now", "syncthing.service")
    print(json.dumps({"installed": VERSION, "archive_sha256_verified": True,
                      "service": run("systemctl", "--user", "is-active", "syncthing.service"),
                      "initial_shared_folders": 0, "gui": "loopback only"}))


def pair(args):
    api = API()
    own = api.call("system/status")["myID"]
    peer = args.peer.strip()
    if peer == own or len(peer) != 63 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567-" for c in peer):
        raise RuntimeError("Invalid peer ID")
    path = pathlib.Path(args.path).expanduser().absolute()
    if path not in (HOME / "work-sync-plane", HOME / "sync-plane") or path.is_symlink():
        raise RuntimeError("Expected dedicated native work-share path")
    folders = api.call("config/folders")
    existing = next((f for f in folders if f["id"] == FOLDER), None)
    for folder in folders:
        other = pathlib.Path(folder["path"]).expanduser().absolute()
        if folder["id"] != FOLDER and (other == path or other in path.parents or path in other.parents):
            raise RuntimeError("Refusing overlapping Syncthing folders")
    if existing and (pathlib.Path(existing["path"]) != path or
                     set(d["deviceID"] for d in existing["devices"]) != {own, peer}):
        raise RuntimeError("Existing share differs; refusing replacement")
    devices = api.call("config/devices")
    device = next((d for d in devices if d["deviceID"] == peer), None)
    api.backup()
    if device is None:
        device = api.call("config/defaults/device")
        device.update(deviceID=peer, name=args.name, addresses=["dynamic"],
                      introducer=False, autoAcceptFolders=False)
        api.call("config/devices", device, "POST")
    if existing is None:
        if path.exists() and any(path.iterdir()):
            raise RuntimeError("Nonempty unconfigured destination; review before pairing")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder = api.call("config/defaults/folder")
        folder.update(id=FOLDER, label="Work Configuration", path=str(path),
                      type="sendreceive", devices=[{"deviceID": own}, {"deviceID": peer}],
                      versioning={"type": "staggered", "params": {"maxAge": "2592000"},
                                  "cleanupIntervalS": 3600, "fsPath": "", "fsType": "basic"})
        api.call("config/folders", folder, "POST")
    print(json.dumps({"dedicated_share_configured": True, "member_count": 2,
                      "restart_required": api.call("config/restart-required")["requiresRestart"]}))


def status():
    api = API()
    folders = api.call("config/folders")
    folder = next((f for f in folders if f["id"] == FOLDER), None)
    result = {"version": api.call("system/version")["version"], "work_share_configured": folder is not None}
    if folder:
        db = api.call("db/status?folder=" + FOLDER)
        result.update({k: db.get(k) for k in ("state", "localFiles", "needFiles", "needBytes", "pullErrors")})
        connections = api.call("system/connections")["connections"]
        own = api.call("system/status")["myID"]
        result["peer_connected"] = all(connections.get(d["deviceID"], {}).get("connected", False)
                                        for d in folder["devices"] if d["deviceID"] != own)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="Fresh Linux x86_64 user-local bootstrap only")
    commands.add_parser("identity", help="Print public Syncthing device ID, never API key")
    commands.add_parser("status", help="Counts and health for the work share only")
    cmd = commands.add_parser("pair", help="Add only the dedicated two-device work share")
    cmd.add_argument("--peer", required=True)
    cmd.add_argument("--name", required=True)
    cmd.add_argument("--path", required=True)
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "identity":
        print(API().call("system/status")["myID"])
    elif args.command == "pair":
        pair(args)
    else:
        status()


if __name__ == "__main__":
    main()
