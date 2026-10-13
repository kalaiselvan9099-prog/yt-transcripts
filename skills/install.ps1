<#
  Install these Agent Skills for every AI agent on this PC (safe to re-run; overwrites older copies).
    powershell -ExecutionPolicy Bypass -File .\skills\install.ps1

  ~\.agents\skills  -> Codex, Cursor, GitHub Copilot / VS Code
  ~\.claude\skills  -> Claude Code (Cursor reads it too)
  Claude desktop / claude.ai: upload each folder as a skill in Claude's skills settings.
#>
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$targets = @("$HOME\.agents\skills", "$HOME\.claude\skills")
Get-ChildItem -Path $src -Directory | Where-Object { Test-Path (Join-Path $_.FullName "SKILL.md") } | ForEach-Object {
  foreach ($t in $targets) {
    $dest = Join-Path $t $_.Name
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item -Path (Join-Path $_.FullName "*") -Destination $dest -Recurse -Force
    Write-Host "installed $($_.Name) -> $dest"
  }
}
Write-Host "Restart your AI apps to pick up the skills."
