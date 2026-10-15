# Turns the laptop's Mobile Hotspot on or off, or prints its network name (name) or name and
# password on two lines (wifi, for the QR code). Usage: hotspot.ps1 on|off|name|wifi
param([Parameter(Mandatory)][ValidateSet('on', 'off', 'name', 'wifi')][string]$Mode)
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$null = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$resultType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]

$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if (-not $profile) { 'no internet connection to share'; exit 1 }
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$config = $manager.GetCurrentAccessPointConfiguration()
if ($Mode -eq 'name') { $config.Ssid; exit 0 }
if ($Mode -eq 'wifi') { $config.Ssid; $config.Passphrase; exit 0 }
$isOn = $manager.TetheringOperationalState -eq 'On'

if ($Mode -eq 'on' -and -not $isOn) { $op = $manager.StartTetheringAsync() }
elseif ($Mode -eq 'off' -and $isOn) { $op = $manager.StopTetheringAsync() }
else { "already $Mode"; exit 0 }

$task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($op))
$null = $task.Wait(30000)
"$Mode -> $($task.Result.Status) $($task.Result.AdditionalErrorMessage)"
