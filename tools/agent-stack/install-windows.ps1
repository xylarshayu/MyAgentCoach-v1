$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CodexHome = Join-Path $env:USERPROFILE ".codex"
$Config = Join-Path $CodexHome "config.toml"
$Guidance = Join-Path $CodexHome "AGENTS.md"
$Stamp = Get-Date -Format "yyyyMMddTHHmmss"

New-Item -ItemType Directory -Force -Path $CodexHome | Out-Null
if (Test-Path $Config) { Copy-Item $Config "$Config.bak.$Stamp" }
if (Test-Path $Guidance) { Copy-Item $Guidance "$Guidance.bak.$Stamp" }
Copy-Item (Join-Path $PSScriptRoot "global-guidance.md") $Guidance -Force

if (-not (Test-Path $Config)) { New-Item -ItemType File -Path $Config | Out-Null }
$Text = Get-Content -Raw $Config
$Blocks = @(
  @("[mcp_servers.openaiDeveloperDocs]", @'

[mcp_servers.openaiDeveloperDocs]
url = "https://developers.openai.com/mcp"
required = false
'@),
  @("[mcp_servers.reddit-mcp-buddy]", @'

[mcp_servers.reddit-mcp-buddy]
command = "wsl.exe"
args = ["-d", "Ubuntu-22.04", "--", "/home/xylar/.local/bin/reddit-mcp-buddy"]
startup_timeout_sec = 60
tool_timeout_sec = 120
required = false
'@),
  @("[agents]", @'

[agents]
max_threads = 4
max_depth = 1
'@)
)

foreach ($Block in $Blocks) {
  if (-not $Text.Contains($Block[0])) { Add-Content -Path $Config -Value $Block[1]; $Text += $Block[1] }
}

$Skills = @(
  "\\wsl.localhost\Ubuntu-22.04\home\xylar\.agents\skills\twitterapi-io",
  "\\wsl.localhost\Ubuntu-22.04\home\xylar\.agents\skills\live-research-plane",
  "\\wsl.localhost\Ubuntu-22.04\home\xylar\.agents\skills\delegate-to-opencode"
)
foreach ($Skill in $Skills) {
  if (-not $Text.Contains($Skill)) {
    Add-Content -Path $Config -Value "`n[[skills.config]]`npath = '$Skill'`nenabled = true`n"
    $Text += $Skill
  }
}

Write-Output "Windows Codex configuration updated. Restart Codex Desktop before verification."
