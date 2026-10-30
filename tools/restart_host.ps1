# Restarts only the listen-server host (RPCS3 in D:\rpcs3) and leaves the CREST server, the offline service and a
# second RPCS3 copy running. The web admin (dust_server/admin.py) calls this after a game-mode change, which the
# running host cannot do in place; the new host runs the start command saved in dust_server\dev_commands.json.
#   .\restart_host.ps1
#   .\restart_host.ps1 -Rpcs3 D:\rpcs3\rpcs3.exe -GameArgs "-autologinserver=127.0.0.1:8080 -autologincharindex=0 -novsync"
param(
    [string]$Rpcs3 = "D:\rpcs3\rpcs3.exe",
    [string]$GameArgs = "-autologinserver=127.0.0.1:8080 -autologincharindex=0 -novsync",
    [string]$Monitor = "\\.\DISPLAY1"
)

Get-Process rpcs3 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Rpcs3 } | ForEach-Object {
    Stop-Process -Id $_.Id -Force
    $_.WaitForExit(10000) | Out-Null
}
& (Join-Path $PSScriptRoot "start_dust.ps1") -Rpcs3 $Rpcs3 -GameArgs $GameArgs -Monitor $Monitor
