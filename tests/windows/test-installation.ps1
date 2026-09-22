$ErrorActionPreference = 'Stop'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "[FAIL] $Message" }
    Write-Output "[PASS] $Message"
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$python = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$pwsh = (Get-Command pwsh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$bundledRuntime = Join-Path $root 'runtime\python.exe'
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("jl-mixing-windows-install-{0}" -f [Guid]::NewGuid().ToString('N'))
$prefix = Join-Path $tempRoot 'prefix'
$profile = Join-Path $tempRoot 'profile\Microsoft.PowerShell_profile.ps1'
$workspace = Join-Path $tempRoot 'workspace'
$originalPath = $env:PATH
$originalTestPython = $env:JL_MIXING_TEST_PYTHON
$originalTestProfile = $env:JL_MIXING_TEST_PROFILE
$originalRoot = $env:JL_MIXING_ROOT
$originalFailure = $env:JL_MIXING_TEST_FAIL_INSTALL_AT

try {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $profile) | Out-Null
    Set-Content -LiteralPath $profile -Value "# user profile content`r`n" -NoNewline -Encoding utf8
    $env:JL_MIXING_TEST_PROFILE = $profile

    $expectedTestRuntime = -not (Test-Path -LiteralPath $bundledRuntime -PathType Leaf)
    if ($expectedTestRuntime) {
        $env:JL_MIXING_TEST_PYTHON = $python
    } else {
        Remove-Item Env:JL_MIXING_TEST_PYTHON -ErrorAction SilentlyContinue
    }

    & $pwsh -NoProfile -File (Join-Path $root 'windows\install.ps1') -Prefix $prefix | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'Windows installer succeeds'

    $app = Join-Path $prefix 'share\jl-mixing'
    $bin = Join-Path $prefix 'bin'
    Assert-True (Test-Path -LiteralPath (Join-Path $app 'VERSION') -PathType Leaf) 'installed application contains VERSION'
    Assert-True (Test-Path -LiteralPath (Join-Path $app 'src\jl_mixing\__init__.py') -PathType Leaf) 'installed application contains Python package'
    Assert-True (Test-Path -LiteralPath (Join-Path $bin 'jl-mixing.cmd') -PathType Leaf) 'installed jl-mixing launcher exists'
    Assert-True (Test-Path -LiteralPath (Join-Path $bin 'jl-mixing-shell-integration.ps1') -PathType Leaf) 'installed PowerShell integration exists'
    if (-not $expectedTestRuntime) {
        Assert-True (Test-Path -LiteralPath (Join-Path $app 'runtime\python.exe') -PathType Leaf) 'installer copies bundled Windows runtime'
    }

    $state = Get-Content -LiteralPath (Join-Path $app 'install-state.json') -Raw | ConvertFrom-Json
    Assert-True ($state.installation_prefix -eq [IO.Path]::GetFullPath($prefix)) 'install state records prefix'
    Assert-True ($state.shell_integration.enabled -eq $true) 'install state records shell integration'
    Assert-True ($state.test_runtime -eq $expectedTestRuntime) 'install state records runtime mode'

    $profileText = Get-Content -LiteralPath $profile -Raw
    Assert-True ($profileText -match '# user profile content') 'installer preserves user PowerShell profile content'
    Assert-True (([regex]::Matches($profileText, '# >>> JL Mixing managed configuration >>>')).Count -eq 1) 'installer adds one managed PowerShell block'

    $env:PATH = "$bin;$originalPath"
    $systemInfoText = & (Join-Path $bin 'jl-mixing.cmd') system-info --json | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'installed jl-mixing launcher runs'
    $systemInfo = $systemInfoText | ConvertFrom-Json
    Assert-True ($systemInfo.api_version -eq '1.0') 'installed dispatcher reports API 1.0'

    & (Join-Path $bin 'new-studio.cmd') --root $workspace --name 'Installed Windows Studio' --no-default-cd | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'installed new-studio creates workspace'
    Assert-True (Test-Path -LiteralPath (Join-Path $workspace 'Studio\studio.json') -PathType Leaf) 'installed new-studio writes configuration'

    $env:JL_MIXING_ROOT = $workspace
    & (Join-Path $bin 'new-client.cmd') installed-client --name 'Installed Client' --no-cd | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'installed new-client creates client'
    Assert-True (Test-Path -LiteralPath (Join-Path $workspace 'Clients\Installed Client\client.json') -PathType Leaf) 'installed client configuration exists'

    & $pwsh -NoProfile -File (Join-Path $root 'windows\install.ps1') -Prefix $prefix | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'Windows reinstall succeeds'
    $profileText = Get-Content -LiteralPath $profile -Raw
    Assert-True (([regex]::Matches($profileText, '# >>> JL Mixing managed configuration >>>')).Count -eq 1) 'reinstall keeps one managed PowerShell block'

    $sentinel = Join-Path $app 'rollback-sentinel.txt'
    Set-Content -LiteralPath $sentinel -Value 'stable' -Encoding utf8
    $env:JL_MIXING_TEST_FAIL_INSTALL_AT = 'after-application'
    & $pwsh -NoProfile -File (Join-Path $root 'windows\install.ps1') -Prefix $prefix 2>$null | Out-Null
    Assert-True ($LASTEXITCODE -ne 0) 'injected Windows install failure is reported'
    Remove-Item Env:JL_MIXING_TEST_FAIL_INSTALL_AT -ErrorAction SilentlyContinue
    Assert-True (Test-Path -LiteralPath $sentinel -PathType Leaf) 'failed reinstall restores previous application'
    Assert-True ((Get-Content -LiteralPath $sentinel -Raw).Trim() -eq 'stable') 'rollback preserves previous application bytes'
    Assert-True ((Get-Content -LiteralPath $profile -Raw) -match '# user profile content') 'rollback preserves PowerShell profile content'

    & $pwsh -NoProfile -File (Join-Path $app 'windows\uninstall.ps1') -Prefix $prefix | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'Windows uninstaller succeeds'
    Assert-True (-not (Test-Path -LiteralPath $app)) 'uninstaller removes application'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $bin 'jl-mixing.cmd'))) 'uninstaller removes managed launcher'
    Assert-True (Test-Path -LiteralPath (Join-Path $workspace 'Studio\studio.json') -PathType Leaf) 'uninstaller preserves studio workspace'
    $profileText = Get-Content -LiteralPath $profile -Raw
    Assert-True ($profileText -match '# user profile content') 'uninstaller preserves user profile content'
    Assert-True ($profileText -notmatch '# >>> JL Mixing managed configuration >>>') 'uninstaller removes managed PowerShell block'

    $global:LASTEXITCODE = 0
    Write-Output '[OK] Windows installation lifecycle'
} finally {
    $env:PATH = $originalPath
    if ($null -eq $originalTestPython) { Remove-Item Env:JL_MIXING_TEST_PYTHON -ErrorAction SilentlyContinue } else { $env:JL_MIXING_TEST_PYTHON = $originalTestPython }
    if ($null -eq $originalTestProfile) { Remove-Item Env:JL_MIXING_TEST_PROFILE -ErrorAction SilentlyContinue } else { $env:JL_MIXING_TEST_PROFILE = $originalTestProfile }
    if ($null -eq $originalRoot) { Remove-Item Env:JL_MIXING_ROOT -ErrorAction SilentlyContinue } else { $env:JL_MIXING_ROOT = $originalRoot }
    if ($null -eq $originalFailure) { Remove-Item Env:JL_MIXING_TEST_FAIL_INSTALL_AT -ErrorAction SilentlyContinue } else { $env:JL_MIXING_TEST_FAIL_INSTALL_AT = $originalFailure }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
