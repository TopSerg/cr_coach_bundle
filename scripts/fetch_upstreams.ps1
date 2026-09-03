param(
    [string]$Root = (Get-Location).Path
)
$ErrorActionPreference = "Stop"
$Dest = Join-Path $Root "upstream"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

function Clone-Repo([string]$Url, [string]$Name) {
    $Path = Join-Path $Dest $Name
    if (Test-Path (Join-Path $Path ".git")) {
        Write-Host "[update] $Name"
        git -C $Path pull --ff-only
        git -C $Path submodule update --init --recursive
    } else {
        Write-Host "[clone] $Name"
        git clone --depth 1 --recurse-submodules --shallow-submodules $Url $Path
    }
}

Clone-Repo "https://github.com/Keschler/cr-bot.git" "cr-bot"
Clone-Repo "https://github.com/cochon123/clash-royale-ai.git" "clash-royale-ai"
Clone-Repo "https://github.com/wty-yy/KataCR.git" "KataCR"
Clone-Repo "https://github.com/RoyaleAPI/cr-api-data.git" "cr-api-data"
Clone-Repo "https://github.com/nguiaSoren/clash-royale-suite.git" "clash-royale-suite"
Clone-Repo "https://github.com/voonhous/crforge.git" "crforge"
Clone-Repo "https://github.com/max-miller1204/Clash-Royale-Pod.git" "Clash-Royale-Pod"
Clone-Repo "https://github.com/smlbiobot/cr-csv.git" "cr-csv"
Clone-Repo "https://github.com/Greedycell/AstralRoyaleLegacy.git" "AstralRoyaleLegacy"
Clone-Repo "https://github.com/retroroyale/ClashRoyale.git" "RetroRoyale"
Clone-Repo "https://github.com/Jason-XII/clash-royale-simulator.git" "clash-royale-simulator"
Clone-Repo "https://github.com/samdickson22/clash-simulator.git" "clash-simulator"
Clone-Repo "https://github.com/krazyness/CRBot-public.git" "CRBot-public"

Write-Host "Done. Upstreams in: $Dest"
