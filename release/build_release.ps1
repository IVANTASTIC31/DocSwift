param(
    [string]$Version = "0.3.1"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$OutputRoot = Join-Path $ProjectRoot "dist\release"
$WorkRoot = Join-Path $ProjectRoot "build\release"
$PackageName = "DocSwift-v$Version-windows-portable"
$PackageRoot = Join-Path $OutputRoot $PackageName
$ArchivePath = Join-Path $OutputRoot "$PackageName.zip"
$ChecksumsPath = Join-Path $OutputRoot "CHECKSUMS-SHA256.TXT"
$IconPath = Join-Path $ProjectRoot "assets\docswift.ico"
$IconPngPath = Join-Path $ProjectRoot "assets\docswift-icon.png"

if ($Version -notmatch "^\d+\.\d+\.\d+$") {
    throw "Version must use the 1.2.3 format."
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Create it and install requirements first."
}

$DeclaredVersion = & $Python -c "from app_version import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0 -or $DeclaredVersion.Trim() -ne $Version) {
    throw "app_version.py is $DeclaredVersion but the requested release is $Version."
}

& $Python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing. Run: .venv\Scripts\python -m pip install pyinstaller==6.16.0"
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name DocSwift `
    --icon $IconPath `
    --add-data "$IconPngPath;assets" `
    --distpath (Join-Path $WorkRoot "dist") `
    --workpath (Join-Path $WorkRoot "work") `
    --specpath $WorkRoot `
    (Join-Path $ProjectRoot "app.py")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

if (Test-Path -LiteralPath $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageRoot | Out-Null
Copy-Item `
    -Path (Join-Path $WorkRoot "dist\DocSwift\*") `
    -Destination $PackageRoot `
    -Recurse `
    -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "portable-readme.txt") -Destination $PackageRoot

if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $ArchivePath

$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash *$PackageName.zip" | Set-Content -LiteralPath $ChecksumsPath -Encoding ascii

Write-Host "Release package: $ArchivePath" -ForegroundColor Green
Write-Host "Checksums:      $ChecksumsPath" -ForegroundColor Green
Write-Host "Next: run release\\prepare_internal_manifest.ps1 -Version $Version." -ForegroundColor Cyan
