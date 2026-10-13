<#
  yt-transcripts - Windows setup (safe to re-run; it repairs/upgrades in place).

  Run from this folder:
    powershell -ExecutionPolicy Bypass -File .\setup.ps1

  Options:
    -Clients "claude,cursor,codex,vscode,claude-code"   which AI apps to register (default: all)
    -NoTasks     don't create the scheduled tasks (auto-resume every 30 min, weekly YouTube-layer update)
#>
param(
  [string]$Clients = "claude,cursor,codex,vscode,claude-code",
  [switch]$NoTasks
)
$ErrorActionPreference = "Stop"
$Repo     = Split-Path -Parent $MyInvocation.MyCommand.Path
$YttHome  = Join-Path $env:LOCALAPPDATA "ytt"
$Venv     = Join-Path $YttHome "venv"
$Py       = Join-Path $Venv "Scripts\python.exe"
$Pyw      = Join-Path $Venv "Scripts\pythonw.exe"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Have($cmd) { $c = Get-Command $cmd -ErrorAction SilentlyContinue; return ($c -and $c.Source -notmatch "WindowsApps") }

# 1. Package manager -------------------------------------------------------------
Step "Checking scoop"
if (-not (Have "scoop")) {
  Write-Host "scoop not found. Install it first (one line, no admin):" -ForegroundColor Yellow
  Write-Host "  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned; irm get.scoop.sh | iex"
  exit 1
}

# 2. Runtimes: Python (core), git (PO-token plugin source), Deno + Node (YouTube JS challenges / PO tokens)
Step "Installing runtimes (python, git, deno, node) if missing"
foreach ($pair in @(@("python","python"), @("git","git"), @("deno","deno"), @("node","nodejs-lts"))) {
  if (-not (Have $pair[0])) { scoop install $pair[1] } else { Write-Host "  $($pair[0]) ok" }
}
$env:Path = [Environment]::GetEnvironmentVariable("Path","User") + ";" + [Environment]::GetEnvironmentVariable("Path","Machine")

# 3. Private virtual environment (isolated from any other Python on the PC) ----------
Step "Creating/refreshing virtual environment at $Venv"
New-Item -ItemType Directory -Force -Path $YttHome | Out-Null
if (-not (Test-Path $Py)) { python -m venv $Venv }
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet --upgrade -e "$Repo[pot]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 4. YouTube layer: latest yt-dlp + EJS solver + PO-token plugin, and build the matching PO-token server
Step "Updating YouTube layer + building PO-token provider (first run takes a few minutes)"
& $Py -m yt_transcripts update

# 5. `ytt` command on PATH ---------------------------------------------------------
Step "Adding ytt to your PATH"
$scripts = Join-Path $Venv "Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path","User")
if ($userPath -notlike "*$scripts*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$scripts", "User")
  Write-Host "  added (open a new terminal to use 'ytt')"
} else { Write-Host "  already on PATH" }

# 6. Register the MCP server in AI apps (configs are backed up first) --------------
Step "Registering MCP server in: $Clients"
& $Py -m yt_transcripts install-clients @($Clients.Split(",") | ForEach-Object { $_.Trim() })

# 6b. Agent Skills (note-making + YouTube-notes workflow) for Claude Code, Codex, Cursor, Copilot
Step "Installing Agent Skills"
& (Join-Path $Repo "skills\install.ps1")

# 7. Scheduled tasks: resume interrupted jobs + keep up with YouTube changes --------
if (-not $NoTasks) {
  Step "Creating scheduled tasks"
  schtasks /Create /F /SC MINUTE /MO 30 /TN "ytt-recover" /TR "`"$Pyw`" -m yt_transcripts recover" | Out-Null
  schtasks /Create /F /SC WEEKLY /D SUN /ST 11:00 /TN "ytt-update" /TR "`"$Pyw`" -m yt_transcripts update" | Out-Null
  Write-Host "  ytt-recover (every 30 min) and ytt-update (Sundays 11:00) created"
}

# 8. Health check -------------------------------------------------------------------
Step "Health check"
& $Py -m yt_transcripts doctor
Write-Host "`nDone. Restart Claude / Cursor / Codex / VS Code, then try:  ytt doctor --live CXGGF4ls1JU" -ForegroundColor Green
