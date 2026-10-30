# Brings the game window of one RPCS3 copy to the front and holds a key, e.g. V = Triangle (Smart Deploy) with RPCS3's
# default keyboard pad. RPCS3 only reads the keyboard of the focused window, so the window takes focus for a moment.
#   .\press_key.ps1 -Rpcs3 D:\rpcs3_b\rpcs3.exe -Key V
#   .\press_key.ps1 -Rpcs3 D:\rpcs3_c\rpcs3.exe -Key X -HoldMs 300
param(
    [Parameter(Mandatory)][string]$Rpcs3,
    [string]$Key = "V",
    [int]$HoldMs = 250
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Kbd {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint mapType);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
"@
$proc = Get-Process rpcs3 -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $Rpcs3 -and $_.MainWindowTitle -like "*NPUB30643*" } | Select-Object -First 1
if (-not $proc) { throw "No DUST 514 window for $Rpcs3." }
$vk = [byte][char]$Key.ToUpper()
$scan = [byte][Kbd]::MapVirtualKey($vk, 0)
[Kbd]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
# Windows refuses SetForegroundWindow to a background process unless it just had input: a short Alt tap counts.
[Kbd]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
[Kbd]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
[Kbd]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 300
if ([Kbd]::GetForegroundWindow() -ne $proc.MainWindowHandle) { throw "Could not bring the window of $Rpcs3 to the front." }
[Kbd]::keybd_event($vk, $scan, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds $HoldMs
[Kbd]::keybd_event($vk, $scan, 2, [UIntPtr]::Zero)   # KEYEVENTF_KEYUP
"$Key sent to $Rpcs3 (pid $($proc.Id))"
