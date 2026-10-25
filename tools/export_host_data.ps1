# Builds the data folder for the Docker battle host (docker/README.md) from the local installation:
# game (with our patched COMMON.SDAT and SAKE.INI), firmware, user profile with license, game patches,
# RPCS3 config for a headless Null-renderer host, and the extracted client modules for catma_service.
# Copy the result to the server (e.g. scp -r / rsync) as $DUST_DATA.
#   .\export_host_data.ps1 -Out E:\dust514-data
#   .\export_host_data.ps1 -Out E:\dust514-data -RpcnConfig D:\rpcs3_host\config\rpcn.yml
# The host needs its own RPCN account (one account cannot be logged in twice). Without -RpcnConfig,
# put an rpcn.yml for that account into <Out>\rpcs3\config\rpcs3\ yourself.
param(
    [Parameter(Mandatory)][string]$Out,
    [string]$Rpcs3 = "D:\rpcs3",
    [string]$RpcnConfig = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $Out "rpcs3\config\rpcs3"   # = $XDG_CONFIG_HOME/rpcs3 inside the container

function Copy-Tree([string]$From, [string]$To) {
    robocopy $From $To /E /NFL /NDL /NJH /NJS /NP /XD "*locks" | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To failed ($LASTEXITCODE)" }
}

Copy-Tree "$Rpcs3\dev_hdd0\game\NPUB30643" "$target\dev_hdd0\game\NPUB30643"
Copy-Tree "$Rpcs3\dev_hdd0\home" "$target\dev_hdd0\home"
Copy-Tree "$Rpcs3\dev_flash" "$target\dev_flash"
Copy-Tree "$Rpcs3\patches" "$target\patches"
# Linux RPCS3 keeps its yml files directly in $target (the Windows build uses a config\ subfolder)
New-Item -ItemType Directory -Force "$target\custom_configs" | Out-Null
Copy-Item "$Rpcs3\config\patch_config.yml" "$target\"

# Game config: the tested Null-renderer config, adjusted for the patched build in the container
$cfg = Get-Content "$Rpcs3\config\custom_configs\config_NPUB30643.yml.null_host" -Raw
$cfg = $cfg -replace '(?m)^(  Frame limit: ).*$', '${1}Auto'        # the flip patch makes the workaround unnecessary
$cfg = $cfg -replace '(?m)^(Audio:\r?\n(?:  .*\r?\n)*?  Renderer: ).*$', '${1}"Null"'
[IO.File]::WriteAllText("$target\custom_configs\config_NPUB30643.yml", $cfg, (New-Object Text.UTF8Encoding $false))

if ($RpcnConfig) { Copy-Item $RpcnConfig "$target\rpcn.yml" }

Copy-Tree "$root\research\extracted_0319" (Join-Path $Out "extracted_0319")

$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
"data folder ready: $Out ({0:N1} GB)" -f $size
if (-not (Test-Path "$target\rpcn.yml")) { "missing: $target\rpcn.yml (RPCN account for the host)" }

exit 0
