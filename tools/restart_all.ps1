# Stops the game, the dev server and the offline service, archives the logs of the last run, starts
# the offline service (Python 2.7, port 8090) and the server again (hidden, console output in
# logs\*_console.log) and, unless -ServerOnly, starts the game.
#   .\restart_all.ps1 -Label vault_fix
#   .\restart_all.ps1 -ServerOnly
param(
    [string]$Label = "run",
    [switch]$ServerOnly
)

$root = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root "dust_server"
$offlineService = Join-Path $root "catma_service"
$py27 = Join-Path $PSScriptRoot "py27\python.exe"
$logs = Join-Path $server "logs"

function Wait-Port([int]$Port, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
    }
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

Get-Process rpcs3 -ErrorAction SilentlyContinue | Stop-Process -Force
Get-NetTCPConnection -State Listen -LocalPort 8080, 8090 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archive = Join-Path $logs "archive\${stamp}_$Label"
foreach ($name in "requests.jsonl", "client.log", "server_console.log", "offline_service_console.log") {
    $file = Join-Path $logs $name
    if (Test-Path $file) {
        New-Item -ItemType Directory -Force $archive | Out-Null
        Move-Item $file $archive
    }
}

Start-Process -FilePath $py27 -ArgumentList "-O", "offline_service.py" -WorkingDirectory $offlineService -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs "offline_service_console.log") -RedirectStandardError (Join-Path $logs "offline_service_errors.log")
if (-not (Wait-Port 8090 60)) { throw "Offline service did not start, see $logs\offline_service_errors.log" }

Start-Process -FilePath python -ArgumentList "listen_server.py" -WorkingDirectory $server -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs "server_console.log") -RedirectStandardError (Join-Path $logs "server_errors.log")
if (-not (Wait-Port 8080 20)) { throw "Server did not start, see $logs\server_errors.log" }
"offline service and server running (logs archived to $archive)"

if (-not $ServerOnly) {
    & (Join-Path $PSScriptRoot "start_dust.ps1")
}
