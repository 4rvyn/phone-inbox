# One-time setup on Windows. Installs what the receiver needs, opens the firewall for the iPhone
# (local network only) and prints the URL to put into the iPhone shortcut. Safe to run again.
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
function Step($text) { Write-Host "`n> $text" -ForegroundColor Cyan }

Step 'Python 3'
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python 3 was not found. Install it from python.org (it includes the "py" launcher), then run this again.'
}
$python = & py -3 -c "import sys; print(sys.executable)"
"  $python"

Step 'QR code library (segno)'
& $python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('segno') else 1)"
if ($LASTEXITCODE -eq 0) { '  already installed' }
else { & $python -m pip install --user --quiet segno; '  installed' }

Step 'ExifTool (reads when each photo or video was taken)'
if ((Get-Command exiftool -ErrorAction SilentlyContinue) -or (Test-Path "$env:LOCALAPPDATA\Programs\ExifTool\exiftool.exe")) {
    '  already installed'
} else {
    winget install --id OliverBetz.ExifTool -e --accept-source-agreements --accept-package-agreements
}

Step 'Firewall rule (lets the iPhone reach this PC on port 8765, local network only)'
if (Get-NetFirewallRule -DisplayName 'Phone inbox' -ErrorAction SilentlyContinue) {
    '  already there'
} else {
    '  Windows will ask for administrator permission once.'
    $rule = "New-NetFirewallRule -DisplayName 'Phone inbox' -Description 'phone-inbox: receive photos from the iPhone' " +
            "-Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -RemoteAddress LocalSubnet -Profile Private,Public"
    Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile', '-Command', $rule
    if (-not (Get-NetFirewallRule -DisplayName 'Phone inbox' -ErrorAction SilentlyContinue)) {
        throw 'The firewall rule was not added (was the administrator prompt declined?).'
    }
    '  added'
}

Step 'Done. Put this URL into the iPhone shortcut (see README):'
& $python (Join-Path $here 'server.py') --info
