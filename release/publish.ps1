[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version,

    [string]$Notes,
    [string]$NotesFile,
    [string]$CommitMessage,

    [switch]$PlanOnly,
    [switch]$Yes,
    [switch]$SkipGitPublish,
    [switch]$SkipGiteaRelease,
    [switch]$SkipServerUpload
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $PSScriptRoot "publish.config.psd1"
$BuildScript = Join-Path $PSScriptRoot "build_release.ps1"
$ManifestScript = Join-Path $PSScriptRoot "prepare_internal_manifest.ps1"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$AppVersionPath = Join-Path $ProjectRoot "app_version.py"
$ReadmePath = Join-Path $ProjectRoot "README.md"
$TagName = "v$Version"
$AssetName = "DocSwift-v$Version-windows-portable.zip"
$OutputRoot = Join-Path $ProjectRoot "dist\release"
$AssetPath = Join-Path $OutputRoot $AssetName
$ChecksumPath = Join-Path $OutputRoot "CHECKSUMS-SHA256.TXT"
$ManifestPath = Join-Path $OutputRoot "latest.json"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

function Get-GitOutput {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
    return ($output -join "`n").Trim()
}

function Set-Utf8Text {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Set-ReleaseVersion {
    $versionText = [System.IO.File]::ReadAllText($AppVersionPath)
    $updatedVersionText = [regex]::Replace(
        $versionText,
        '(?m)^__version__\s*=\s*"[^"]+"\s*$',
        "__version__ = `"$Version`""
    )
    $expectedVersionLine = '__version__ = "' + $Version + '"'
    if ($updatedVersionText -eq $versionText -and -not $versionText.Contains($expectedVersionLine)) {
        throw "Could not update app_version.py."
    }
    Set-Utf8Text -Path $AppVersionPath -Content $updatedVersionText

    $readmeText = [System.IO.File]::ReadAllText($ReadmePath)
    $readmeVersionPattern = '(?m)(^- .+`v)\d+\.\d+\.\d+(`.*$)'
    $updatedReadmeText = [regex]::Replace(
        $readmeText,
        $readmeVersionPattern,
        {
            param($match)
            return $match.Groups[1].Value + $Version + $match.Groups[2].Value
        },
        1
    )
    if ($updatedReadmeText -eq $readmeText -and $readmeText -notmatch [regex]::Escape("``v$Version``")) {
        throw "Could not update the current version in README.md."
    }
    Set-Utf8Text -Path $ReadmePath -Content $updatedReadmeText
}

function Invoke-GiteaJson {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "DELETE")]
        [string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body
    )
    $uri = "$($Config.GiteaBaseUrl.TrimEnd('/'))$Path"
    $headers = @{
        Authorization = "token $GiteaToken"
        Accept = "application/json"
    }
    $parameters = @{
        Uri = $uri
        Method = $Method
        Headers = $headers
        UseBasicParsing = $true
    }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json"
        $parameters.Body = ($Body | ConvertTo-Json -Depth 8)
    }
    return Invoke-RestMethod @parameters
}

function Get-GiteaRelease {
    try {
        return Invoke-GiteaJson `
            -Method GET `
            -Path "/api/v1/repos/$($Config.GiteaOwner)/$($Config.GiteaRepository)/releases/tags/$TagName"
    }
    catch {
        $statusCode = $null
        if ($null -ne $_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        if ($statusCode -eq 404) {
            return $null
        }
        throw
    }
}

function Add-GiteaAsset {
    param(
        [Parameter(Mandatory = $true)][long]$ReleaseId,
        [Parameter(Mandatory = $true)][string]$FilePath
    )
    Add-Type -AssemblyName System.Net.Http
    $client = New-Object System.Net.Http.HttpClient
    $client.DefaultRequestHeaders.Add("Authorization", "token $GiteaToken")
    $client.DefaultRequestHeaders.Add("Accept", "application/json")
    $fileStream = $null
    $multipart = $null
    try {
        $fileStream = [System.IO.File]::OpenRead($FilePath)
        $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
        $fileContent.Headers.ContentType = New-Object System.Net.Http.Headers.MediaTypeHeaderValue("application/octet-stream")
        $multipart = New-Object System.Net.Http.MultipartFormDataContent
        $multipart.Add($fileContent, "attachment", [System.IO.Path]::GetFileName($FilePath))
        $uri = "$($Config.GiteaBaseUrl.TrimEnd('/'))/api/v1/repos/$($Config.GiteaOwner)/$($Config.GiteaRepository)/releases/$ReleaseId/assets?name=$([uri]::EscapeDataString([System.IO.Path]::GetFileName($FilePath)))"
        $response = $client.PostAsync($uri, $multipart).GetAwaiter().GetResult()
        $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "Gitea asset upload failed: $([int]$response.StatusCode) $responseBody"
        }
    }
    finally {
        if ($null -ne $multipart) {
            $multipart.Dispose()
        }
        elseif ($null -ne $fileStream) {
            $fileStream.Dispose()
        }
        $client.Dispose()
    }
}

function Publish-GiteaRelease {
    Write-Step "Create or update the company Gitea release"
    $release = Get-GiteaRelease
    if ($null -eq $release) {
        $release = Invoke-GiteaJson `
            -Method POST `
            -Path "/api/v1/repos/$($Config.GiteaOwner)/$($Config.GiteaRepository)/releases" `
            -Body @{
                tag_name = $TagName
                target_commitish = $Config.CompanyBranch
                name = "DocSwift $TagName"
                body = $ReleaseNotes
                draft = $false
                prerelease = $false
            }
        Write-Host "Created Gitea release $TagName." -ForegroundColor Green
    }
    else {
        Write-Host "Gitea release $TagName already exists; checking assets." -ForegroundColor Yellow
    }

    foreach ($filePath in @($AssetPath, $ChecksumPath)) {
        $file = Get-Item -LiteralPath $filePath
        $existing = @($release.assets | Where-Object { $_.name -eq $file.Name }) | Select-Object -First 1
        if ($null -ne $existing -and [long]$existing.size -eq $file.Length) {
            Write-Host "Asset already present with matching size: $($file.Name)"
            continue
        }
        if ($null -ne $existing) {
            Invoke-GiteaJson `
                -Method DELETE `
                -Path "/api/v1/repos/$($Config.GiteaOwner)/$($Config.GiteaRepository)/releases/$($release.id)/assets/$($existing.id)" | Out-Null
            Write-Host "Removed stale Gitea asset: $($file.Name)" -ForegroundColor Yellow
        }
        Add-GiteaAsset -ReleaseId $release.id -FilePath $file.FullName
        Write-Host "Uploaded Gitea asset: $($file.Name)" -ForegroundColor Green
    }
}

function Publish-InternalServer {
    Write-Step "Upload the package to the company update server"
    $destination = "$($Config.ServerUser)@$($Config.ServerHost)"
    $remoteStage = "/home/$($Config.ServerUser)/docswift-$TagName"
    $remoteRelease = "$($Config.UpdateRoot)/releases/$TagName"
    $expectedHash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA256).Hash.ToLowerInvariant()

    Invoke-Checked `
        -Command "ssh" `
        -Arguments @("-o", "BatchMode=yes", $destination, "mkdir -p '$remoteStage'")
    Invoke-Checked `
        -Command "scp" `
        -Arguments @(
            "-o",
            "BatchMode=yes",
            $AssetPath,
            $ManifestPath,
            "${destination}:$remoteStage/"
        )

    $remoteCommand = @(
        "set -eu",
        "mkdir -p '$remoteRelease'",
        "install -m 0644 '$remoteStage/$AssetName' '$remoteRelease/$AssetName'",
        "echo '$expectedHash  $remoteRelease/$AssetName' | sha256sum -c -",
        "install -m 0644 '$remoteStage/latest.json' '$($Config.UpdateRoot)/latest.json'",
        "rm -rf '$remoteStage'"
    ) -join "; "
    Invoke-Checked `
        -Command "ssh" `
        -Arguments @("-o", "BatchMode=yes", $destination, $remoteCommand)

    Write-Step "Verify the employee-facing update endpoints"
    $publicManifestUrl = "$($Config.PublicUpdateBaseUrl.TrimEnd('/'))/latest.json"
    $publicAssetUrl = "$($Config.PublicUpdateBaseUrl.TrimEnd('/'))/releases/$TagName/$AssetName"
    $publishedManifest = Invoke-RestMethod -Uri $publicManifestUrl -UseBasicParsing
    if ($publishedManifest.version -ne $Version) {
        throw "Published manifest version is $($publishedManifest.version), expected $Version."
    }
    if ($publishedManifest.sha256 -ne $expectedHash) {
        throw "Published manifest SHA-256 does not match the local package."
    }
    $head = Invoke-WebRequest -Uri $publicAssetUrl -Method Head -UseBasicParsing
    if ([long]$head.Headers["Content-Length"] -ne (Get-Item -LiteralPath $AssetPath).Length) {
        throw "Published package size does not match the local package."
    }
    Write-Host "Internal update endpoint verified: $publicManifestUrl" -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Missing release configuration: $ConfigPath"
}
$Config = Import-PowerShellDataFile -LiteralPath $ConfigPath

if ([string]::IsNullOrWhiteSpace($Notes) -and [string]::IsNullOrWhiteSpace($NotesFile)) {
    throw "Provide either -Notes or -NotesFile."
}
if (-not [string]::IsNullOrWhiteSpace($NotesFile)) {
    $resolvedNotesFile = Resolve-Path -LiteralPath $NotesFile
    $ReleaseNotes = [System.IO.File]::ReadAllText($resolvedNotesFile)
}
else {
    $ReleaseNotes = $Notes
}
if ([string]::IsNullOrWhiteSpace($ReleaseNotes)) {
    throw "Release notes cannot be empty."
}
if ([string]::IsNullOrWhiteSpace($CommitMessage)) {
    $CommitMessage = "Release DocSwift $TagName"
}

Push-Location $ProjectRoot
try {
    Write-Step "Validate the local release environment"
    foreach ($commandName in @("git", "ssh", "scp")) {
        if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "Required command is missing: $commandName"
        }
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Missing project Python environment: $Python"
    }
    $remoteUrl = Get-GitOutput remote get-url $Config.CompanyRemote
    if ([string]::IsNullOrWhiteSpace($remoteUrl)) {
        throw "Git remote '$($Config.CompanyRemote)' is not configured."
    }
    $currentBranch = Get-GitOutput branch --show-current
    if ([string]::IsNullOrWhiteSpace($currentBranch)) {
        throw "Publishing from a detached HEAD is not supported."
    }
    $statusBefore = Get-GitOutput status --short

    Write-Host "Version:       $TagName"
    Write-Host "Branch:        $currentBranch -> $($Config.CompanyRemote)/$($Config.CompanyBranch)"
    Write-Host "Gitea:         $($Config.GiteaBaseUrl)/$($Config.GiteaOwner)/$($Config.GiteaRepository)"
    Write-Host "Update server: $($Config.ServerUser)@$($Config.ServerHost):$($Config.UpdateRoot)"
    Write-Host "Git changes:"
    if ([string]::IsNullOrWhiteSpace($statusBefore)) {
        Write-Host "  (clean working tree)"
    }
    else {
        $statusBefore -split "`n" | ForEach-Object { Write-Host "  $_" }
    }

    if (-not $SkipGiteaRelease) {
        $GiteaToken = $env:DOCSWIFT_GITEA_TOKEN
        if ([string]::IsNullOrWhiteSpace($GiteaToken)) {
            Write-Warning "DOCSWIFT_GITEA_TOKEN is not configured."
            if (-not $PlanOnly) {
                throw "Set DOCSWIFT_GITEA_TOKEN or use -SkipGiteaRelease."
            }
        }
    }
    if (-not $SkipServerUpload) {
        Write-Host "SSH publishing requires key-based, non-interactive access."
    }

    if ($PlanOnly) {
        Write-Host ""
        Write-Host "Plan check completed. No files, Git refs, releases, or server data were changed." -ForegroundColor Green
        return
    }

    if (-not $Yes) {
        Write-Host ""
        $confirmation = Read-Host "Type RELEASE $TagName to continue"
        if ($confirmation -ne "RELEASE $TagName") {
            throw "Publishing cancelled."
        }
    }

    Write-Step "Update version metadata"
    Set-ReleaseVersion

    Write-Step "Run syntax checks and the complete regression suite"
    $previousPythonUtf8 = $env:PYTHONUTF8
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:PYTHONUTF8 = "1"
        $env:QT_QPA_PLATFORM = "offscreen"
        Invoke-Checked `
            -Command $Python `
            -Arguments @(
                "-m",
                "py_compile",
                "app.py",
                "domain.py",
                "preview_service.py",
                "project_store.py",
                "services.py",
                "logging_config.py"
            )
        Invoke-Checked `
            -Command $Python `
            -Arguments @("-m", "unittest", "discover", "-s", "tests", "-v")
    }
    finally {
        $env:PYTHONUTF8 = $previousPythonUtf8
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }

    Write-Step "Build the Windows portable package"
    Invoke-Checked `
        -Command "powershell" `
        -Arguments @(
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $BuildScript,
            "-Version",
            $Version
        )

    Write-Step "Generate the internal update manifest"
    Invoke-Checked `
        -Command "powershell" `
        -Arguments @(
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $ManifestScript,
            "-Version",
            $Version,
            "-BaseUrl",
            $Config.PublicUpdateBaseUrl,
            "-Notes",
            $ReleaseNotes
        )

    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $asset = Get-Item -LiteralPath $AssetPath
    $assetHash = (Get-FileHash -LiteralPath $AssetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($manifest.version -ne $Version -or
        [long]$manifest.size -ne $asset.Length -or
        $manifest.sha256 -ne $assetHash) {
        throw "Local release manifest verification failed."
    }

    if (-not $SkipGitPublish) {
        Write-Step "Commit, tag, and push only to the company Gitea remote"
        Invoke-Checked -Command "git" -Arguments @("add", "-A")
        & git diff --cached --quiet
        if ($LASTEXITCODE -eq 1) {
            Invoke-Checked -Command "git" -Arguments @("commit", "-m", $CommitMessage)
        }
        elseif ($LASTEXITCODE -ne 0) {
            throw "Could not inspect staged Git changes."
        }
        else {
            Write-Host "No source changes require a new commit."
        }

        $headCommit = Get-GitOutput rev-parse HEAD
        & git show-ref --verify --quiet "refs/tags/$TagName"
        $tagLookupExitCode = $LASTEXITCODE
        if ($tagLookupExitCode -eq 0) {
            $existingTagCommit = Get-GitOutput rev-list -n 1 $TagName
            if ($existingTagCommit.Trim() -ne $headCommit) {
                throw "Tag $TagName already points to another commit."
            }
            Write-Host "Tag $TagName already points to the current commit."
        }
        elseif ($tagLookupExitCode -ne 1) {
            throw "Unable to inspect Git tag $TagName."
        }
        else {
            Invoke-Checked `
                -Command "git" `
                -Arguments @("tag", "-a", $TagName, "-m", "DocSwift $TagName")
        }

        Invoke-Checked `
            -Command "git" `
            -Arguments @(
                "push",
                $Config.CompanyRemote,
                "HEAD:$($Config.CompanyBranch)"
            )
        Invoke-Checked `
            -Command "git" `
            -Arguments @("push", $Config.CompanyRemote, $TagName)
    }

    if (-not $SkipGiteaRelease) {
        Publish-GiteaRelease
    }
    if (-not $SkipServerUpload) {
        Publish-InternalServer
    }

    Write-Host ""
    $externalStepsSkipped = (
        $SkipGitPublish -and
        $SkipGiteaRelease -and
        $SkipServerUpload
    )
    if ($externalStepsSkipped) {
        Write-Host(
            "DocSwift $TagName local release validation completed successfully."
        ) -ForegroundColor Green
    }
    else {
        Write-Host "DocSwift $TagName published successfully." -ForegroundColor Green
    }
    Write-Host "Package: $AssetPath"
    Write-Host "SHA-256: $assetHash"
}
finally {
    Pop-Location
}
