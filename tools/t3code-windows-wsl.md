# T3 Code: Windows desktop with a WSL2 agent backend

Last verified: 2026-08-02 with T3 Code `0.0.31`, Windows 11, WSL `2.7.11`, and
Ubuntu 22.04.

## Goal

Use the native Windows T3 Code desktop UI while projects, terminals, Git state, provider CLIs,
authentication, chats, and T3's server data remain inside WSL2.

The working architecture is:

```text
Windows T3 desktop
  local bootstrap: http://127.0.0.1:3773
  paired remote environment
    -> WSL T3 service: http://127.0.0.1:3774
       -> ~/.t3/userdata/state.sqlite
       -> Codex / Claude Code / OpenCode inside WSL
```

The Windows-local backend exists so the Electron app can open. Day-to-day agent work should be
created in the paired WSL environment.

## Why not T3's built-in WSL backend?

On the verified machine, T3's built-in WSL launch repeatedly behaved as follows:

1. The desktop launched `wsl.exe` and waited for its backend.
2. Readiness checks against port 3773 failed for 60 seconds.
3. The desktop timed out and remained on the connecting screen.
4. The WSL server initialized only after the timeout and became healthy too late for the desktop
   to recover.

Mirrored networking fixed Windows-to-WSL localhost routing, but not this startup handoff. The
separate WSL service plus remote-environment pairing avoids the failing handoff entirely.

This is an early-product workaround, not a claim that every T3/WSL version has the same bug. Try
the built-in integration again after relevant T3 releases.

## Prerequisites

Inside WSL:

```sh
node --version
codex --version
claude --version
opencode --version
systemctl --user is-system-running
```

T3 currently requires Node `^22.16 || ^23.11 || >=24.10`. Only the providers actually being used
need to be installed and authenticated. Authenticate them inside WSL, because that is where the
agent processes run.

Install the Windows desktop app:

```powershell
winget install T3Tools.T3Code
```

## 1. Enable mirrored WSL networking

In `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Preserve any existing processor, memory, swap, or experimental settings in the file. Apply the
change from PowerShell:

```powershell
wsl --shutdown
```

After WSL restarts, a Linux server bound to loopback should be reachable from Windows through the
same loopback port.

## 2. Disable the desktop's built-in WSL backend

If T3 opens normally, turn off its WSL backend in Settings. If it is trapped on the connecting
screen, close T3 and edit `%USERPROFILE%\.t3\userdata\desktop-settings.json` from PowerShell:

```powershell
$path = Join-Path $env:USERPROFILE '.t3\userdata\desktop-settings.json'
Copy-Item $path "$path.before-wsl-remote.bak" -Force
$settings = Get-Content $path -Raw | ConvertFrom-Json
$settings.wslBackendEnabled = $false
$settings.wslOnly = $false
$json = $settings | ConvertTo-Json -Compress -Depth 20
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path, $json, $utf8)
```

Do not delete `~/.t3` inside WSL. It contains the WSL server's persistent state.

## 3. Install the WSL background service

First enable systemd lingering. This is the one step that may require the Linux account password:

```sh
sudo loginctl enable-linger "$USER"
npx t3@latest service install
npx t3@latest service status
```

Lingering lets the per-user service survive after the last WSL terminal closes. On a deliberately
on-demand setup it is optional, provided the launch helper starts the service whenever needed.

### Reserve port 3774 for WSL

The Windows-local T3 backend normally uses port 3773. Configure the WSL unit to use loopback port
3774 so the two environments never compete for a port.

Inspect the generated unit:

```sh
systemctl --user cat t3code.service
```

In `~/.config/systemd/user/t3code.service`, keep the installer-generated absolute Node and T3
entry paths, but make the `ExecStart` line end with:

```text
serve --host 127.0.0.1 --port 3774
```

Then reload and restart it:

```sh
systemctl --user daemon-reload
systemctl --user enable --now t3code.service
curl -fsS http://127.0.0.1:3774/.well-known/t3/environment
```

From PowerShell, verify the Windows side too:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3774/.well-known/t3/environment
```

Both probes should return HTTP 200. Keep the WSL service loopback-only unless remote network access
is intentionally configured and secured.

### If `service install` fails at `enable-linger`

The installer may successfully download a pinned runtime and then roll the service back because
unprivileged `loginctl enable-linger` was denied. Run the `sudo loginctl` command above and retry.

If lingering is intentionally unavailable, manually create the user unit using the same structure
as T3's generated unit:

```ini
[Unit]
Description=T3 Code server (WSL remote environment)
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=%h
Environment=T3CODE_HOME=%h/.t3
Environment=T3_BOOT_SERVICE_UNIT=t3code.service
ExecStart=/absolute/path/to/node /absolute/path/to/t3/dist/bin.mjs serve --host 127.0.0.1 --port 3774
Restart=always
RestartSec=5
StandardOutput=append:%h/.t3/userdata/logs/boot-service.log
StandardError=append:%h/.t3/userdata/logs/boot-service.log

[Install]
WantedBy=default.target
```

Use the real paths from the failed install under `~/.t3/runtime/versions/<version>/`; do not copy a
username or Node-version path from another computer.

## 4. Pair WSL with the Windows desktop

Start the desktop normally. It should now open using its Windows-local backend.

With T3 `0.0.31`, mint a one-time pairing URL inside WSL:

```sh
npx t3@latest auth pairing create \
  --base-url http://127.0.0.1:3774 \
  --label "Windows desktop"
```

Newer T3 releases may also provide the shorter command:

```sh
npx t3@latest pair
```

Treat the generated URL/token as a credential: do not commit it, paste it into chat, or retain it
in shell scripts. In the desktop app, open **Settings -> Connections -> Remote Environments -> Add
environment** and paste the full pairing URL.

When creating a project or conversation, select the Linux/WSL environment rather than the local
Windows environment.

## 5. Daily launch command

A convenient `~/.local/bin/t3-up` can:

1. start `t3code.service`;
2. wait for `http://127.0.0.1:3774/.well-known/t3/environment`;
3. launch the Windows Electron app with PowerShell.

The verified home-machine helper is installed locally at `~/.local/bin/t3-up`; it is intentionally
not copied verbatim here because the Windows installation path and pinned Node/T3 paths can differ
between computers.

After creating the equivalent helper on another machine, daily use is simply:

```sh
t3-up
```

Useful checks:

```sh
systemctl --user is-active t3code.service
systemctl --user status t3code.service
tail -n 100 ~/.t3/userdata/logs/boot-service.log
curl -fsS http://127.0.0.1:3774/.well-known/t3/environment
```

## Updating

Finish active agent work before updating. The official update command is:

```sh
npx t3@latest service update
```

After an update:

1. inspect `systemctl --user cat t3code.service`;
2. reapply the loopback port-3774 arguments if the installer replaced them;
3. update any helper that contains pinned Node or T3 version paths;
4. restart and rerun both readiness probes;
5. update the Windows desktop so client and server versions remain compatible.

## Data and backup locations

- WSL server state: `~/.t3/userdata/state.sqlite`
- WSL server logs: `~/.t3/userdata/logs/`
- WSL service: `~/.config/systemd/user/t3code.service`
- Windows desktop settings: `%USERPROFILE%\.t3\userdata\desktop-settings.json`
- Electron profile/cache: `%APPDATA%\t3code`

Running through `npx` does not make chats ephemeral. T3's state lives in its data directory, not in
the npm package cache. Preserve `~/.t3` when reinstalling or changing how the server is launched.
