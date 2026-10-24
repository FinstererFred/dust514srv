# Starts DUST 514 in RPCS3 (optional) and places the game window as a small window on another monitor.
#   .\start_dust.ps1                                   start the game and move its window
#   .\start_dust.ps1 -MoveOnly                         only move an already running game window
#   .\start_dust.ps1 -Monitor \\.\DISPLAY3 -Fullscreen  fullscreen on that monitor (RPCS3's Alt+Enter)
#   .\start_dust.ps1 -GameArgs "-benchmark"            command line for the game (shows up in RPCS3's TTY.log)
#   .\start_dust.ps1 -Rpcs3 D:\rpcs3_b\rpcs3.exe -GameArgs "-autologinserver=127.0.0.1:8081"
#                                                     second instance (multiplayer test): own copy, port 8081, no PSN
param(
    [switch]$MoveOnly,
    [switch]$Fullscreen,
    [string]$GameArgs = "",
    [string]$Monitor = "\\.\DISPLAY1",
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$Margin = 80,
    [string]$Rpcs3 = "D:\rpcs3\rpcs3.exe",
    [string]$Eboot = ""
)
if (-not $Eboot) { $Eboot = Join-Path (Split-Path $Rpcs3) "dev_hdd0\game\NPUB30643\USRDIR\EBOOT.BIN" }

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
# Physical pixel coordinates; otherwise monitors with different scaling get mixed up.
[Win]::SetProcessDPIAware() | Out-Null

if (-not $MoveOnly) {
    # "--" ends RPCS3's own options, so game arguments like -benchmark reach the game unparsed.
    $rpcsArgs = @('--no-gui')
    if ($Fullscreen) {
        # RPCS3 (Qt) numbers the primary screen 0, then the others in Windows' enumeration order.
        $screens = [System.Windows.Forms.Screen]::AllScreens
        $ordered = @($screens | Where-Object { $_.Primary }) + @($screens | Where-Object { -not $_.Primary })
        $index = [array]::IndexOf(($ordered | ForEach-Object { $_.DeviceName }), $Monitor)
        $rpcsArgs += @('--fullscreen', '--game-screen', [string]$index)
    }
    $rpcsArgs += @("`"$Eboot`"")
    if ($GameArgs) { $rpcsArgs += @('--') + @($GameArgs -split ' ' | Where-Object { $_ }) }
    Start-Process -FilePath $Rpcs3 -ArgumentList $rpcsArgs -WorkingDirectory (Split-Path $Rpcs3) | Out-Null
}

# The game window title contains the title ID once the game is booted.
$deadline = (Get-Date).AddSeconds(60)
do {
    # Only the instance from $Rpcs3, so that a second RPCS3 copy can run next to it.
    $proc = Get-Process rpcs3 -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $Rpcs3 -and $_.MainWindowTitle -like "*NPUB30643*" } | Select-Object -First 1
    if (-not $proc) { Start-Sleep -Milliseconds 500 }
} until ($proc -or (Get-Date) -gt $deadline)
if (-not $proc) { throw "No RPCS3 window with DUST 514 found." }

$screen = [System.Windows.Forms.Screen]::AllScreens | Where-Object { $_.DeviceName -eq $Monitor } | Select-Object -First 1
if (-not $screen) { throw "Monitor $Monitor not found." }
$x = $screen.WorkingArea.X + $Margin
$y = $screen.WorkingArea.Y + $Margin

if ($Fullscreen) {
    "DUST 514 fullscreen on $Monitor"
} else {
    [Win]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null   # SW_RESTORE: leave maximized/fullscreen state
    [Win]::SetWindowPos($proc.MainWindowHandle, [IntPtr]::Zero, $x, $y, $Width, $Height, 0x0014) | Out-Null  # SWP_NOZORDER | SWP_NOACTIVATE
    "DUST 514 window at $x,$y ($Width x $Height) on $Monitor"
}
