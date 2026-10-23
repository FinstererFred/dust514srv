# Starts DUST 514 in RPCS3 (optional) and places the game window as a small window on another monitor.
#   .\start_dust.ps1                 start the game and move its window
#   .\start_dust.ps1 -MoveOnly       only move an already running game window
param(
    [switch]$MoveOnly,
    [string]$Monitor = "\\.\DISPLAY1",
    [int]$Width = 1280,
    [int]$Height = 720,
    [int]$Margin = 80,
    [string]$Rpcs3 = "D:\rpcs3\rpcs3.exe",
    [string]$Eboot = "D:\rpcs3\dev_hdd0\game\NPUB30643\USRDIR\EBOOT.BIN"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
"@

if (-not $MoveOnly) {
    Start-Process -FilePath $Rpcs3 -ArgumentList '--no-gui', "`"$Eboot`"" -WorkingDirectory (Split-Path $Rpcs3) | Out-Null
}

# The game window title contains the title ID once the game is booted.
$deadline = (Get-Date).AddSeconds(60)
do {
    $proc = Get-Process rpcs3 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "*NPUB30643*" } | Select-Object -First 1
    if (-not $proc) { Start-Sleep -Milliseconds 500 }
} until ($proc -or (Get-Date) -gt $deadline)
if (-not $proc) { throw "No RPCS3 window with DUST 514 found." }

$screen = [System.Windows.Forms.Screen]::AllScreens | Where-Object { $_.DeviceName -eq $Monitor } | Select-Object -First 1
if (-not $screen) { throw "Monitor $Monitor not found." }
$x = $screen.WorkingArea.X + $Margin
$y = $screen.WorkingArea.Y + $Margin

[Win]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null   # SW_RESTORE: leave maximized/fullscreen state
[Win]::SetWindowPos($proc.MainWindowHandle, [IntPtr]::Zero, $x, $y, $Width, $Height, 0x0014) | Out-Null  # SWP_NOZORDER | SWP_NOACTIVATE
"DUST 514 window at $x,$y ($Width x $Height) on $Monitor"
