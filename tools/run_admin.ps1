# Lance un script Python en PowerShell ADMIN (requis pour ReadProcessMemory/WriteProcessMemory
# sur Cemu) et capture la sortie dans tmp/run_admin_out.txt.
#
# Usage (depuis un shell non-eleve) :
#   powershell -ExecutionPolicy Bypass -File tools\run_admin.ps1 tools/scan_all_nodes.py
#   powershell -ExecutionPolicy Bypass -File tools\run_admin.ps1 tools/live_insert_item.py --commit
#
# Puis lire la sortie : tmp/run_admin_out.txt (encodage UTF-16LE).

$proj = Split-Path $PSScriptRoot -Parent
$out  = Join-Path $proj 'tmp\run_admin_out.txt'
Remove-Item $out -ErrorAction SilentlyContinue

$py  = ($args -join ' ')
$cmd = "cd '$proj'; python $py *>&1 | Tee-Object -FilePath '$out'; Start-Sleep -Milliseconds 300; exit"

Start-Process powershell -Verb RunAs -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd
)
Write-Host "Lance en admin: python $py  -> sortie dans tmp/run_admin_out.txt"
