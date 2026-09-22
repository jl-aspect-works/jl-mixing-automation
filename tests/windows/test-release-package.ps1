$ErrorActionPreference = 'Stop'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "[FAIL] $Message" }
    Write-Output "[PASS] $Message"
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$pwsh = (Get-Command pwsh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("jl-mixing-windows-release-test-{0}" -f [Guid]::NewGuid().ToString('N'))
$dist = Join-Path $tempRoot 'dist'
$extract = Join-Path $tempRoot 'extract'
$prefix = Join-Path $tempRoot 'prefix'
$profile = Join-Path $tempRoot 'profile\Microsoft.PowerShell_profile.ps1'
$archive = Join-Path $dist "jl-mixing-$version-windows.zip"
$checksum = "$archive.sha256"
$inventory = "$archive.inventory.txt"
$packageRoot = Join-Path $extract "jl-mixing-$version"
$originalProfile = $env:JL_MIXING_TEST_PROFILE

try {
    New-Item -ItemType Directory -Force -Path $dist, $extract, (Split-Path -Parent $profile) | Out-Null
    Set-Content -LiteralPath $profile -Value "# package test profile`r`n" -NoNewline -Encoding utf8
    $env:JL_MIXING_TEST_PROFILE = $profile

    & $pwsh -NoProfile -File (Join-Path $root 'windows\build-release.ps1') -OutputDir $dist | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'Windows release builder succeeds'
    Assert-True (Test-Path -LiteralPath $archive -PathType Leaf) 'Windows release ZIP exists'
    Assert-True (Test-Path -LiteralPath $checksum -PathType Leaf) 'Windows release checksum exists'
    Assert-True (Test-Path -LiteralPath $inventory -PathType Leaf) 'Windows release inventory exists'

    $expectedHash = ((Get-Content -LiteralPath $checksum -Raw).Trim() -split '\s+')[0]
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-True ($expectedHash -eq $actualHash) 'Windows release checksum verifies'

    Expand-Archive -LiteralPath $archive -DestinationPath $extract
    Assert-True (Test-Path -LiteralPath (Join-Path $packageRoot 'runtime\python.exe') -PathType Leaf) 'extracted package contains bundled runtime'
    Assert-True (Test-Path -LiteralPath (Join-Path $packageRoot 'windows\install.ps1') -PathType Leaf) 'extracted package contains Windows installer'
    Assert-True (Test-Path -LiteralPath (Join-Path $packageRoot 'RELEASE_MANIFEST.txt') -PathType Leaf) 'extracted package contains release manifest'

    & $pwsh -NoProfile -File (Join-Path $packageRoot 'windows\install.ps1') -Prefix $prefix | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'extracted Windows release installs'

    $installedCommand = Join-Path $prefix 'bin\jl-mixing.cmd'
    $systemInfoText = & $installedCommand system-info --json | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'installed release command runs through bundled runtime'
    $systemInfo = $systemInfoText | ConvertFrom-Json
    Assert-True ($systemInfo.api_version -eq '1.0') 'installed release reports API 1.0'
    Assert-True ($systemInfo.application.version -eq $version) 'installed release reports package VERSION'

    & $pwsh -NoProfile -File (Join-Path $prefix 'share\jl-mixing\windows\uninstall.ps1') -Prefix $prefix | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'extracted Windows release uninstalls'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $prefix 'share\jl-mixing'))) 'release uninstall removes installed application'
    Assert-True ((Get-Content -LiteralPath $profile -Raw) -match '# package test profile') 'release lifecycle preserves profile content'

    $global:LASTEXITCODE = 0
    Write-Output '[OK] Windows release package lifecycle'
} finally {
    if ($null -eq $originalProfile) { Remove-Item Env:JL_MIXING_TEST_PROFILE -ErrorAction SilentlyContinue } else { $env:JL_MIXING_TEST_PROFILE = $originalProfile }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
