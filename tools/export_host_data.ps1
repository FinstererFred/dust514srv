# Builds the data folder for the Docker battle host (docs/setup_guide_en.md, docker/README.md) from an RPCS3
# installation with the game, firmware and license: game, firmware, user profile with license and the EdgeZlib patch
# are copied; everything the host needs on top is applied to the copy only, so the source installation stays a
# normal client:
#   - COMMON.SDAT with client_patch/ (dev hook, log forwarding) and DUSTGAME.XXX with the data log patch
#   - SAKE.INI pointing at the stack's CREST server (127.0.0.1:8080)
#   - the host game patches from rpcs3_patches/ as patches/patch.yml, enabled in patch_config.yml
#   - the Null-renderer config from docker/host/config_NPUB30643.yml
#   - the client modules for catma_service, unpacked from the original COMMON.SDAT and PYTHON.SDAT
# Copy the result to the server (e.g. scp -r / rsync) as $DUST_DATA.
#   .\export_host_data.ps1 -Out E:\dust514-data
# Needs Python 3 ($Python) and the Python 2.7 environment in tools\py27 (README.md, "Einrichtung" step 1).
# The host signs in to the stack's own RPCN (docker/rpcn, 127.0.0.1:31313); its watchdog creates the account
# there. rpcn.yml is written once with a random password and on later runs only pointed at that server.
param(
    [Parameter(Mandatory)][string]$Out,
    [string]$Rpcs3 = "D:\rpcs3",
    [string]$RpcnNpid = "DustHost",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $Out "rpcs3\config\rpcs3"   # = $XDG_CONFIG_HOME/rpcs3 inside the container
$game = "$target\dev_hdd0\game\NPUB30643\USRDIR\DUSTGAME"
$utf8 = New-Object Text.UTF8Encoding $false

function Copy-Tree([string]$From, [string]$To) {
    robocopy $From $To /E /NFL /NDL /NJH /NJS /NP /XD "*locks" | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To failed ($LASTEXITCODE)" }
}

function Invoke-Python {
    & $Python @args
    if ($LASTEXITCODE -ne 0) { throw "$Python $args failed ($LASTEXITCODE)" }
}

if (-not (Test-Path "$Rpcs3\dev_hdd0\game\NPUB30643\USRDIR\EBOOT.BIN")) { throw "DUST 514 (NPUB30643) is not installed in $Rpcs3" }
if (-not (Test-Path "$root\tools\py27\python.exe")) { throw "tools\py27 is missing (conda create -p tools\py27 python=2.7)" }

Copy-Tree "$Rpcs3\dev_hdd0\game\NPUB30643" "$target\dev_hdd0\game\NPUB30643"
Copy-Tree "$Rpcs3\dev_hdd0\home" "$target\dev_hdd0\home"
Copy-Tree "$Rpcs3\dev_flash" "$target\dev_flash"
Copy-Tree "$Rpcs3\patches" "$target\patches"
# Linux RPCS3 keeps its yml files directly in $target (the Windows build uses a config\ subfolder)
New-Item -ItemType Directory -Force "$target\custom_configs" | Out-Null

# Game files of the host. Both tools keep the original as *.orig and always patch from it, so reruns are safe
$env:DUST_GAME_DIR = $game
Invoke-Python "$root\tools\patch_common_sdat.py"
Invoke-Python "$root\tools\set_toc_size.py" COMMON.SDAT   # the game checks file sizes against PS3TOC.TXT
Invoke-Python "$root\tools\patch_dustgame_pkg.py"         # same size, no TOC change
Remove-Item Env:\DUST_GAME_DIR
$sake = [IO.File]::ReadAllText("$game\SAKE.INI") -replace '(?m)^url = .*$', 'url = http://127.0.0.1:8080'
[IO.File]::WriteAllText("$game\SAKE.INI", $sake, $utf8)

# Host game patches: one patch.yml next to the copied <serial>_patch.yml (EdgeZlib). RPCS3 merges both files and
# skips an entry that the other file already has in the same version. A patch.yml of the source installation (RPCS3's
# downloaded community patches) is replaced in the copy, so it must not hold the game's own patches.
if ((Test-Path "$Rpcs3\patches\patch.yml") -and (Select-String -Quiet "NPUB30643" "$Rpcs3\patches\patch.yml")) {
    throw "$Rpcs3\patches\patch.yml has DUST 514 patches; move them to NPUB30643_patch.yml in the same folder"
}
$patchYml = "Version: 1.2`n`nPPU-ae3f946dfcb103b782f73f1cc5f90587e652f439:`n"
foreach ($name in "host_full_outpost_lod", "host_disable_world_rendering", "host_rdv_request") {
    # the entry itself, without the file's comment header, Version and PPU hash line
    $text = [IO.File]::ReadAllText("$root\rpcs3_patches\$name.yml") -replace "`r", ""
    $patchYml += $text.Substring([regex]::Match($text, '(?m)^  "').Index).TrimEnd() + "`n"
}
[IO.File]::WriteAllText("$target\patches\patch.yml", $patchYml, $utf8)
$enabled = "Force PPU zlib fallback (EdgeZlib bypass)", "Listen host: load all outpost LODs",
           "Listen host: disable world rendering", "Listen host: allow vehicle requests (RDV)"
$patchConfig = "PPU-ae3f946dfcb103b782f73f1cc5f90587e652f439:`n" + (($enabled | ForEach-Object {
    "  `"$_`":`n    `"DUST 514`":`n      NPUB30643:`n        03.19:`n          Enabled: true`n" }) -join "")
[IO.File]::WriteAllText("$target\patch_config.yml", $patchConfig, $utf8)

# Game config: the tested Null-renderer host config (Frame limit Auto, RPCS3 thread scheduler)
Copy-Item "$root\docker\host\config_NPUB30643.yml" "$target\custom_configs\config_NPUB30643.yml"

$rpcnYml = "$target\rpcn.yml"
$rpcnHost = "127.0.0.1:31313"
if (Test-Path $rpcnYml) {
    $yml = Get-Content $rpcnYml -Raw
    $yml = $yml -replace '(?m)^Host: .*$', "Host: $rpcnHost"
    $yml = $yml -replace '(?m)^Hosts: .*$', "Hosts: `"DUST 514 stack|$rpcnHost`""
} else {
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    $yml = "Version: 2`nHost: $rpcnHost`nNPID: $RpcnNpid`nPassword: $password`nToken: `"`"`n" +
           "Hosts: `"DUST 514 stack|$rpcnHost`"`nExperimental IPv6 support: false`n"
}
[IO.File]::WriteAllText($rpcnYml, $yml, $utf8)

# Client modules for catma_service (the SDATs are plain zip archives)
$extracted = Join-Path $Out "extracted_0319"
$unzip = "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])"
Invoke-Python -c $unzip "$game\COMMON.SDAT.orig" "$extracted\COMMON"
Invoke-Python -c $unzip "$game\PYTHON.SDAT" "$extracted\PYTHON"

$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
"data folder ready: $Out ({0:N1} GB)" -f $size

exit 0
