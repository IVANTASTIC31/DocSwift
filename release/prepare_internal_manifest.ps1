param(
    [string]$Version = "0.3.0",
    [string]$BaseUrl = "http://192.168.100.3/updates/docswift",
    [string]$Notes = "DocSwift v0.3.0: startup feedback, rotating logs, background recognition queue, safer card removal, streamlined controls, and a new application icon."
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputRoot = Join-Path $ProjectRoot "dist\release"
$AssetName = "DocSwift-v$Version-windows-portable.zip"
$AssetPath = Join-Path $OutputRoot $AssetName
$ManifestPath = Join-Path $OutputRoot "latest.json"

if ($Version -notmatch "^\d+\.\d+\.\d+$") {
    throw "Version must use the 1.2.3 format."
}
if (-not (Test-Path -LiteralPath $AssetPath -PathType Leaf)) {
    throw "Release package not found: $AssetPath"
}

$Asset = Get-Item -LiteralPath $AssetPath
$Hash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    manifest_version = 1
    application = "DocSwift"
    channel = "stable"
    version = $Version
    published_at = [DateTimeOffset]::Now.ToString("o")
    download_url = "$($BaseUrl.TrimEnd('/'))/releases/v$Version/$AssetName"
    sha256 = $Hash
    size = $Asset.Length
    mandatory = $false
    notes = $Notes
}

$Manifest |
    ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath $ManifestPath -Encoding utf8

Write-Host "Internal manifest: $ManifestPath" -ForegroundColor Green
Write-Host "SHA-256:          $Hash" -ForegroundColor Green
Write-Host "Size:             $($Asset.Length) bytes" -ForegroundColor Green
