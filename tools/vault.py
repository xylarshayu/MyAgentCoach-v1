"""Encrypt, decrypt, and check the private goal-system vault."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".vault" / "manifest.json"
LOCAL_HAZARDS_PATH = ROOT / ".vault" / "hazards.local.json"
RESTORED_STATE_PATH = ROOT / ".vault" / "restored.json"
KEY_ENV = "MY_DECODE_KEY"
MAGIC = b"GOALOSVAULT1\n"
PBKDF2_ROUNDS = 390_000
TEXT_SUFFIXES = {".md", ".txt", ".toml", ".json", ".py", ".yml", ".yaml"}


class VaultError(Exception):
    """Expected user-facing vault failure."""


@dataclass(frozen=True)
class Manifest:
    vault_path: Path
    private_paths: tuple[Path, ...]
    private_roots: tuple[Path, ...]
    public_paths: tuple[Path, ...]
    public_roots: tuple[Path, ...]
    public_scan_excludes: tuple[str, ...]
    hazard_terms: tuple[str, ...]


def load_manifest() -> Manifest:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    version = raw.get("version")
    if version != 1:
        raise VaultError(f"Unsupported manifest version: {version!r}")

    explicit_private_paths = tuple(_clean_relative_path(item) for item in raw.get("private_paths", ()))
    private_roots = tuple(_clean_relative_path(item) for item in raw.get("private_roots", ()))
    public_paths = tuple(_clean_relative_path(item) for item in raw.get("public_paths", ()))
    public_roots = tuple(_clean_relative_path(item) for item in raw.get("public_roots", ()))
    public_scan_excludes = tuple(raw.get("public_scan_excludes", ()))
    private_paths = resolve_private_paths(explicit_private_paths, private_roots, public_paths, public_roots, public_scan_excludes)
    if len(set(private_paths)) != len(private_paths):
        raise VaultError("Manifest contains duplicate private paths.")

    hazard_terms = list(raw.get("hazard_terms", ()))
    if LOCAL_HAZARDS_PATH.exists():
        local_raw = json.loads(LOCAL_HAZARDS_PATH.read_text(encoding="utf-8"))
        hazard_terms.extend(local_raw.get("hazard_terms", ()))

    return Manifest(
        vault_path=_clean_relative_path(raw["vault_path"]),
        private_paths=private_paths,
        private_roots=private_roots,
        public_paths=public_paths,
        public_roots=public_roots,
        public_scan_excludes=public_scan_excludes,
        hazard_terms=tuple(hazard_terms),
    )


def _clean_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise VaultError(f"Manifest path must stay inside the repo: {value}")
    return path


def repo_path(path: Path) -> Path:
    return ROOT / path


def require_key() -> str:
    key = os.environ.get(KEY_ENV)
    if not key:
        key = load_env_key()
    if not key:
        raise VaultError(f"{KEY_ENV} is not set. Export it or add it to .env before using the vault.")
    return key


def load_env_key() -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != KEY_ENV:
            continue
        return clean_env_value(value.strip())
    return None


def clean_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def resolve_private_paths(
    explicit_paths: Iterable[Path],
    private_roots: Iterable[Path],
    public_paths: Iterable[Path],
    public_roots: Iterable[Path],
    public_scan_excludes: Iterable[str],
) -> tuple[Path, ...]:
    resolved: set[Path] = set()
    for path in explicit_paths:
        if is_private_file_candidate(path, public_paths, public_roots, public_scan_excludes):
            resolved.add(path)

    for root in private_roots:
        full_root = repo_path(root)
        if not full_root.exists():
            continue
        if full_root.is_file():
            if is_private_file_candidate(root, public_paths, public_roots, public_scan_excludes):
                resolved.add(root)
            continue
        for path in full_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if is_private_file_candidate(relative, public_paths, public_roots, public_scan_excludes):
                resolved.add(relative)

    return tuple(sorted(resolved, key=lambda item: item.as_posix()))


def is_private_file_candidate(
    path: Path,
    public_paths: Iterable[Path],
    public_roots: Iterable[Path],
    public_scan_excludes: Iterable[str],
) -> bool:
    relative = path.as_posix()
    if is_excluded(relative, public_scan_excludes):
        return False
    if relative in {item.as_posix() for item in public_paths}:
        return False
    if is_under_any_root(path, public_roots):
        return False
    return repo_path(path).is_file() and repo_path(path).suffix.lower() in TEXT_SUFFIXES


def is_under_any_root(path: Path, roots: Iterable[Path]) -> bool:
    relative = path.as_posix()
    for root in roots:
        root_name = root.as_posix().rstrip("/") + "/"
        if relative == root.as_posix().rstrip("/") or relative.startswith(root_name):
            return True
    return False


def derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        PBKDF2_ROUNDS,
        dklen=64,
    )
    return key_material[:32], key_material[32:]


def run_openssl_crypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    command = [
        "openssl",
        "enc",
        "-aes-256-ctr",
        "-K",
        key.hex(),
        "-iv",
        iv.hex(),
    ]
    proc = subprocess.run(
        command,
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise VaultError(f"OpenSSL failed: {message}")
    return proc.stdout


def encrypt_bytes(plaintext: bytes, passphrase: str) -> bytes:
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(16)
    enc_key, mac_key = derive_keys(passphrase, salt)
    ciphertext = run_openssl_crypt(plaintext, enc_key, iv)
    header = {
        "kdf": "pbkdf2-hmac-sha256",
        "rounds": PBKDF2_ROUNDS,
        "cipher": "aes-256-ctr+hmac-sha256",
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    mac_input = MAGIC + len(header_bytes).to_bytes(4, "big") + header_bytes + ciphertext
    tag = hmac.new(mac_key, mac_input, hashlib.sha256).digest()
    return mac_input + tag


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise VaultError("Vault file has an unknown format.")

    cursor = len(MAGIC)
    header_len = int.from_bytes(blob[cursor : cursor + 4], "big")
    cursor += 4
    header_bytes = blob[cursor : cursor + header_len]
    cursor += header_len
    ciphertext = blob[cursor:-32]
    actual_tag = blob[-32:]

    header = json.loads(header_bytes.decode("utf-8"))
    if header.get("cipher") != "aes-256-ctr+hmac-sha256":
        raise VaultError(f"Unsupported cipher: {header.get('cipher')!r}")
    if header.get("rounds") != PBKDF2_ROUNDS:
        raise VaultError("Unsupported vault KDF rounds.")

    salt = base64.b64decode(header["salt"])
    iv = base64.b64decode(header["iv"])
    enc_key, mac_key = derive_keys(passphrase, salt)
    mac_input = blob[:-32]
    expected_tag = hmac.new(mac_key, mac_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_tag, actual_tag):
        raise VaultError("Vault authentication failed. The key may be wrong or the file may be damaged.")

    return run_openssl_crypt(ciphertext, enc_key, iv)


def build_bundle(manifest: Manifest) -> bytes:
    files: dict[str, str] = {}
    missing: list[str] = []
    for relative_path in manifest.private_paths:
        path = repo_path(relative_path)
        if not path.exists():
            missing.append(str(relative_path))
            continue
        if not path.is_file():
            raise VaultError(f"Private path is not a file: {relative_path}")
        files[str(relative_path)] = path.read_text(encoding="utf-8")

    if missing:
        raise VaultError("Missing private files: " + ", ".join(missing))

    payload = {
        "format": "goal-os-private-bundle",
        "version": 1,
        "files": files,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9)


def unpack_bundle(data: bytes) -> dict[str, str]:
    payload = json.loads(gzip.decompress(data).decode("utf-8"))
    if payload.get("format") != "goal-os-private-bundle" or payload.get("version") != 1:
        raise VaultError("Vault bundle payload is not supported.")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise VaultError("Vault bundle payload is missing files.")
    return {str(path): str(content) for path, content in files.items()}


def command_encrypt(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    passphrase = require_key()
    write_encrypted_vault(manifest, passphrase)
    print(f"Encrypted {len(manifest.private_paths)} private files into {manifest.vault_path}.")
    return 0


def write_encrypted_vault(manifest: Manifest, passphrase: str) -> None:
    bundle = build_bundle(manifest)
    encrypted = encrypt_bytes(bundle, passphrase)
    vault_path = repo_path(manifest.vault_path)
    vault_path.parent.mkdir(parents=True, exist_ok=True)
    vault_path.write_bytes(encrypted)


def command_decrypt(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    passphrase = require_key()
    restore_decrypted_vault(manifest, passphrase)
    print(f"Restored {len(manifest.private_paths)} private files from {manifest.vault_path}.")
    return 0


def restore_decrypted_vault(manifest: Manifest, passphrase: str) -> None:
    files = read_encrypted_vault(manifest, passphrase)
    write_private_files(manifest, files)
    mark_skip_worktree(manifest.private_paths)
    RESTORED_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESTORED_STATE_PATH.write_text(
        json.dumps({"restored_paths": sorted(files)}, indent=2) + "\n",
        encoding="utf-8",
    )


def read_encrypted_vault(manifest: Manifest, passphrase: str) -> dict[str, str]:
    vault_path = repo_path(manifest.vault_path)
    if not vault_path.exists():
        raise VaultError(f"Vault artifact is missing: {manifest.vault_path}")

    files = unpack_bundle(decrypt_bytes(vault_path.read_bytes(), passphrase))
    expected = {str(path) for path in manifest.private_paths}
    actual = set(files)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if extra:
            detail.append("extra: " + ", ".join(extra))
        raise VaultError("Vault contents do not match manifest (" + "; ".join(detail) + ").")
    return files


def write_private_files(manifest: Manifest, files: dict[str, str]) -> None:
    for relative_name, content in files.items():
        relative_path = _clean_relative_path(relative_name)
        path = repo_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def command_publicize(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    publicize_private_files(manifest)
    print(f"Wrote {len(manifest.private_paths)} public placeholder files.")
    return 0


def publicize_private_files(manifest: Manifest) -> None:
    vault_path = repo_path(manifest.vault_path)
    if not vault_path.exists():
        raise VaultError(f"Refusing to publicize before an encrypted vault exists: {manifest.vault_path}")

    clear_skip_worktree(manifest.private_paths)
    for relative_path in manifest.private_paths:
        path = repo_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(public_template_for(relative_path), encoding="utf-8")

    if RESTORED_STATE_PATH.exists():
        RESTORED_STATE_PATH.unlink()


def command_check(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    return check_manifest(manifest)


def check_manifest(manifest: Manifest) -> int:
    failures: list[str] = []

    staged_private = unsafe_staged_manifest_paths(manifest.private_paths)
    if staged_private:
        failures.append("Private paths are staged with non-placeholder content: " + ", ".join(staged_private))

    scan_paths = list(public_scan_paths(manifest))
    for path in scan_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lower_text = text.lower()
        matches = [term for term in manifest.hazard_terms if term.lower() in lower_text]
        if matches:
            relative = path.relative_to(ROOT)
            failures.append(f"{relative}: hazard terms found: {', '.join(matches)}")

    if failures:
        print("Vault check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Vault check passed. Scanned {len(scan_paths)} public files.")
    return 0


def command_sync_pull(_: argparse.Namespace) -> int:
    manifest = load_manifest()
    passphrase = require_key()
    vault_path = repo_path(manifest.vault_path)

    if vault_path.exists() and not private_files_match_vault(manifest, passphrase) and not private_files_are_placeholders(manifest):
        raise VaultError(
            "Private files differ from the encrypted vault. "
            "Run `uv run vault sync-push` first or resolve local private edits manually."
        )

    dirty = non_private_status_paths(manifest)
    if dirty:
        raise VaultError("Refusing to pull with non-private local changes: " + ", ".join(dirty))

    run_git_checked(["pull", "--rebase"])
    restore_decrypted_vault(manifest, passphrase)
    result = check_manifest(manifest)
    if result != 0:
        return result

    print("Sync pull complete. Workspace is decoded.")
    return 0


def command_sync_push(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    passphrase = require_key()
    vault_path = repo_path(manifest.vault_path)
    if vault_path.exists() and private_files_are_placeholders(manifest):
        restore_decrypted_vault(manifest, passphrase)
        manifest = load_manifest()
        print("Restored decoded private files before syncing.")

    vault_needs_update = not vault_path.exists() or not private_files_match_vault(manifest, passphrase)
    if vault_needs_update:
        write_encrypted_vault(manifest, passphrase)
        print(f"Encrypted {len(manifest.private_paths)} private files into {manifest.vault_path}.")
    else:
        print(f"Encrypted vault already matches {len(manifest.private_paths)} private files.")

    publicize_private_files(manifest)
    print(f"Wrote {len(manifest.private_paths)} public placeholder files.")

    try:
        staged_paths = stage_safe_paths(manifest)
    except VaultError as exc:
        restore_decrypted_vault(manifest, passphrase)
        raise VaultError(f"{exc} Workspace restored to decoded mode.") from exc
    if not staged_paths:
        restore_decrypted_vault(manifest, passphrase)
        print("No changes to commit. Workspace is decoded.")
        return 0

    result = check_manifest(manifest)
    if result != 0:
        raise VaultError("Vault check failed. Leaving workspace publicized; run `uv run vault decrypt` after resolving it.")

    try:
        run_git_checked(["commit", "-m", args.message])
        push_current_branch()
    except VaultError as exc:
        raise VaultError(f"{exc} Leaving workspace publicized; run `uv run vault decrypt` after resolving it.") from exc

    restore_decrypted_vault(manifest, passphrase)
    print("Sync push complete. Workspace is decoded.")
    return 0


def private_files_match_vault(manifest: Manifest, passphrase: str) -> bool:
    try:
        encrypted_files = read_encrypted_vault(manifest, passphrase)
    except VaultError as exc:
        if "Vault contents do not match manifest" in str(exc):
            return False
        raise
    current_files: dict[str, str] = {}
    for path in manifest.private_paths:
        full_path = repo_path(path)
        if not full_path.exists() or not full_path.is_file():
            return False
        current_files[path.as_posix()] = full_path.read_text(encoding="utf-8")
    return current_files == encrypted_files


def private_files_are_placeholders(manifest: Manifest) -> bool:
    for path in manifest.private_paths:
        full_path = repo_path(path)
        if not full_path.exists() or not full_path.is_file():
            return False
        if full_path.read_text(encoding="utf-8", errors="ignore") != public_template_for(path):
            return False
    return True


def unsafe_staged_manifest_paths(private_paths: Iterable[Path]) -> list[str]:
    proc = run_git(["diff", "--cached", "--name-only"])
    if proc.returncode != 0:
        return []
    staged = set(proc.stdout.decode("utf-8").splitlines())
    unsafe: list[str] = []
    for path in private_paths:
        name = path.as_posix()
        if name not in staged:
            continue
        if public_template_for(path) != repo_path(path).read_text(encoding="utf-8", errors="ignore"):
            unsafe.append(name)
    return sorted(unsafe)


def public_template_for(path: Path) -> str:
    return public_templates().get(
        path.as_posix(),
        f"""# Private File

This file is restored from the encrypted vault on trusted machines.

Path: `{path.as_posix()}`
""",
    )


def public_scan_paths(manifest: Manifest) -> Iterable[Path]:
    paths = tracked_public_files(manifest)
    paths.extend(staged_public_files(manifest))
    if paths:
        seen: set[Path] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            yield path
        return

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if is_excluded(relative, manifest.public_scan_excludes):
            continue
        if path.suffix.lower() not in {".md", ".txt", ".toml", ".json", ".py", ".yml", ".yaml"}:
            continue
        yield path


def staged_public_files(manifest: Manifest) -> list[Path]:
    paths: list[Path] = []
    for relative in staged_names():
        if is_excluded(relative, manifest.public_scan_excludes):
            continue
        path = repo_path(Path(relative))
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".toml", ".json", ".py", ".yml", ".yaml"}:
            paths.append(path)
    return paths


def tracked_public_files(manifest: Manifest) -> list[Path]:
    proc = run_git(["ls-files", "-v"])
    if proc.returncode != 0:
        return []

    paths: list[Path] = []
    private_names = {path.as_posix() for path in manifest.private_paths}
    for line in proc.stdout.decode("utf-8").splitlines():
        if not line:
            continue
        marker = line[0]
        relative = line[2:]
        if is_excluded(relative, manifest.public_scan_excludes):
            continue
        if marker == "S" and relative in private_names:
            continue
        path = repo_path(Path(relative))
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".toml", ".json", ".py", ".yml", ".yaml"}:
            paths.append(path)
    return paths


def is_excluded(relative: str, excludes: Iterable[str]) -> bool:
    return any(relative == item.rstrip("/") or relative.startswith(item) for item in excludes)


def mark_skip_worktree(paths: Iterable[Path]) -> None:
    tracked = tracked_names()
    target_paths = [str(path) for path in paths if str(path) in tracked]
    if not target_paths:
        return
    proc = run_git(["update-index", "--skip-worktree", *target_paths])
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise VaultError(f"Could not mark restored private files skip-worktree: {message}")


def clear_skip_worktree(paths: Iterable[Path]) -> None:
    tracked = tracked_names()
    target_paths = [str(path) for path in paths if str(path) in tracked]
    if not target_paths:
        return
    proc = run_git(["update-index", "--no-skip-worktree", *target_paths])
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise VaultError(f"Could not clear skip-worktree markers: {message}")


def tracked_names() -> set[str]:
    proc = run_git(["ls-files"])
    if proc.returncode != 0:
        return set()
    return set(proc.stdout.decode("utf-8").splitlines())


def staged_names() -> list[str]:
    proc = run_git(["diff", "--cached", "--name-only"])
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.decode("utf-8").splitlines() if line]


def status_paths() -> list[str]:
    proc = run_git(["status", "--porcelain", "--untracked-files=all"])
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise VaultError(f"Could not read Git status: {message}")

    paths: list[str] = []
    for line in proc.stdout.decode("utf-8").splitlines():
        if not line:
            continue
        raw_path = line[3:]
        if " -> " in raw_path:
            _, raw_path = raw_path.split(" -> ", 1)
        paths.append(raw_path)
    return paths


def non_private_status_paths(manifest: Manifest) -> list[str]:
    return sorted(path for path in status_paths() if not is_private_path(path, manifest))


def stage_safe_paths(manifest: Manifest) -> list[str]:
    private_names = {path.as_posix() for path in manifest.private_paths}
    safe_paths: list[str] = []
    unclassified_paths: list[str] = []

    for path in status_paths():
        if should_skip_sync_stage(path, manifest):
            continue
        if not is_sync_stage_allowed(path, manifest):
            unclassified_paths.append(path)
            continue
        if path in private_names and public_template_for(Path(path)) != repo_path(Path(path)).read_text(encoding="utf-8", errors="ignore"):
            raise VaultError(f"Refusing to stage private path with non-placeholder content: {path}")
        safe_paths.append(path)

    if unclassified_paths:
        raise VaultError(
            "Unclassified files need a private root or public allowlist entry: "
            + ", ".join(sorted(unclassified_paths))
        )

    if not safe_paths:
        return []

    run_git_checked(["add", "--", *safe_paths])
    return safe_paths


def should_skip_sync_stage(path: str, manifest: Manifest) -> bool:
    if path == RESTORED_STATE_PATH.relative_to(ROOT).as_posix():
        return True
    if path == LOCAL_HAZARDS_PATH.relative_to(ROOT).as_posix():
        return True
    if path == ".env":
        return True
    if path.startswith(".git/") or path.startswith(".venv/"):
        return True
    return False


def is_sync_stage_allowed(path: str, manifest: Manifest) -> bool:
    return is_private_path(path, manifest) or is_public_path(path, manifest)


def is_private_path(path: str, manifest: Manifest) -> bool:
    return path in {private_path.as_posix() for private_path in manifest.private_paths}


def is_public_path(path: str, manifest: Manifest) -> bool:
    relative = Path(path)
    return relative in manifest.public_paths or is_under_any_root(relative, manifest.public_roots)


def current_branch() -> str:
    proc = run_git_checked(["branch", "--show-current"])
    branch = proc.stdout.decode("utf-8").strip()
    if not branch:
        raise VaultError("Could not determine the current branch.")
    return branch


def has_upstream() -> bool:
    proc = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    return proc.returncode == 0


def push_current_branch() -> None:
    if has_upstream():
        run_git_checked(["push"])
        return
    run_git_checked(["push", "-u", "origin", current_branch()])


def run_git_checked(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    proc = run_git(args)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        command = "git " + " ".join(args)
        raise VaultError(f"`{command}` failed: {message}")
    return proc


def run_git(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    encrypt = subparsers.add_parser("encrypt", help="Encrypt private files into the committed vault artifact.")
    encrypt.set_defaults(func=command_encrypt)

    decrypt = subparsers.add_parser("decrypt", help="Restore private files from the encrypted vault artifact.")
    decrypt.set_defaults(func=command_decrypt)

    publicize = subparsers.add_parser("publicize", help="Replace private working files with safe public placeholders.")
    publicize.set_defaults(func=command_publicize)

    check = subparsers.add_parser("check", help="Check public plaintext and staged private paths.")
    check.set_defaults(func=command_check)

    sync_pull = subparsers.add_parser("sync-pull", help="Pull latest Git changes and restore decoded private files.")
    sync_pull.set_defaults(func=command_sync_pull)

    sync_push = subparsers.add_parser(
        "sync-push",
        help="Encrypt private files, commit and push safe public state, then restore decoded private files.",
    )
    sync_push.add_argument("-m", "--message", default="Sync goal system state", help="Commit message to use.")
    sync_push.set_defaults(func=command_sync_push)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except VaultError as exc:
        print(f"vault: {exc}", file=sys.stderr)
        return 1


def public_templates() -> dict[str, str]:
    return {
        "context/mission-brief.md": """# Mission Brief

## Purpose

Describe the durable purpose of this goal system in generic terms.

## Starting Situation

Capture non-sensitive context that helps future sessions orient quickly.

## Working Goal Hypotheses

- Goal area:
- Why it matters:
- Current constraint:

## Non-Goals

- 

## Near-Term Thesis

Keep this provisional until enough evidence has been gathered.
""",
        "context/operating-constraints.md": """# Operating Constraints

## Planning Constraints

- 

## Energy And Capacity

- 

## Time Horizon

- Daily:
- Weekly:
- Monthly:
- Quarterly:

## Agent Risk

Agents should avoid over-planning and should end sessions with concrete next actions.
""",
        "context/personal-profile.md": """# Personal Profile

## Known Facts

- 

## Assets

- 

## Constraints

- 

## Unknowns To Clarify

- 
""",
        "dump/01_first_prompt.md": """# Initial Capture

Use this file for raw setup notes that are safe to publish, or restore the private version from the vault.
""",
        "dump/encryption-requirement.md": """# Encryption Requirement

Sensitive working files are encrypted into `vault/private.bundle.enc` using `MY_DECODE_KEY`.

The public repository should remain useful as a template while private files are restorable on trusted machines.
""",
        "observations/2026-06-07-kickoff.md": """# Kickoff Observations

## Raw Context

- 

## Notable Signals

- 

## Candidate Lessons

- 
""",
        "plans/2026-06-kickoff.md": """# Dated Plan

## Status

Undecided pending context gathering.

## Planning Inputs

- 

## Candidate Outputs

- 
""",
        "plans/current.md": """# Current Plan

Current as of:

## Current Phase

- 

## Planning Status

- 

## Active Commitments

- 

## Next Actions

- 
""",
        "research/README.md": """# Research

Use this directory for public-safe research notes, references, and decision support.

Keep sensitive research in the encrypted vault.
""",
        "state/active-backlog.md": """# Active Backlog

Current as of:

| Area | Item | Grain | Status | Urgency | Next Action | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

## Backlog Rules

- Capture first, refine later.
- Do not require a complete inventory before adding known work.
- Move active commitments into `plans/current.md` only after discussion.
""",
        "state/asset-inventory.md": """# Asset Inventory

Current as of:

## Target Direction

- 

## Current Materials

| Asset | Status | Notes | Next Action |
| --- | --- | --- | --- |
| | | | |

## Strongest Evidence

- 

## Gaps

- 

## First Pipeline

- 
""",
        "state/dashboard.md": """# Dashboard

Last updated:

## Overall Status

Phase:

Current priority:

## Tracks

| Track | Status | Current Focus |
| --- | --- | --- |
| | | |

## Immediate Risks

- 

## Current Next Actions

- 

## Agent Notes

- 
""",
        "state/decisions.md": """# Decisions

Use this file for decisions that should persist across sessions.

| Date | Decision | Rationale | Revisit |
| --- | --- | --- | --- |
| | | | |
""",
        "state/open-questions.md": """# Open Questions

These questions should be answered over several sessions, not all at once.

## Current Reality

- 

## Goals

- 

## Constraints

- 

## Support Systems

- 
""",
        "state/pressure-map.md": """# Pressure Map

Current as of:

## Current Reality

- 

## Active Projects

| Project | Deadline | Stakeholders | Risk | Next Required Move |
| --- | --- | --- | --- | --- |
| | | | | |

## People Map

- 

## Delivery Risks

- 

## Minimum Safe Performance

- 

## Questions For Next Session

- 
""",
        "state/risks.md": """# Risks

## Active Risks

### Risk Name

Potential impact:

Mitigation:

- 
""",
        "strategy/README.md": """# Strategy

Use this directory for public-safe strategic framing, tradeoffs, and reusable thinking.

Keep private strategy details in the encrypted vault.
""",
        "strategy/initial-strategy.md": """# Initial Strategy

Date:

## Strategic Frame

- 

## Track 1

Objective:

Likely actions:

- 

## Track 2

Objective:

Likely actions:

- 

## First Strategic Bet

Provisional thought, not yet a decision:
""",
    }


if __name__ == "__main__":
    raise SystemExit(main())
