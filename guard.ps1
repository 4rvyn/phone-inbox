# Started hidden by server.py. Waits until that window's process has ended in any way (closed, crashed,
# killed), then undoes what it may have left behind: the laptop hotspot, if that window had turned it on,
# and half-received files. Does nothing that belongs to a newer window.
param([Parameter(Mandatory)][int]$ParentPid, [Parameter(Mandatory)][string]$Folder)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$marker = Join-Path $here 'hotspot-owned.txt'
$log = Join-Path $here 'inbox.log'
function Write-Log($text) {
    Add-Content -LiteralPath $log -Value ("{0} guard: {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss,fff'), $text) -Encoding utf8
}

try { Wait-Process -Id $ParentPid -ErrorAction Stop } catch { }

# A hotspot switch-on that the window started but didn't see finish would turn it back on later.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe' AND ParentProcessId=$ParentPid" |
    Where-Object { $_.CommandLine -like '*hotspot.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$owner = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { '' }
if ($owner -eq "$ParentPid") {
    $result = & (Join-Path $here 'hotspot.ps1') off 2>&1 | Out-String
    Remove-Item -LiteralPath $marker -ErrorAction SilentlyContinue
    Write-Log "window $ParentPid ended with the hotspot on; $($result.Trim())"
}

Start-Sleep -Seconds 2  # a date read on a half-received file may still be finishing
Get-ChildItem -LiteralPath $Folder -Filter ".incoming-$ParentPid-*.part" -Force -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue; Write-Log "removed half-received $($_.Name)" }
