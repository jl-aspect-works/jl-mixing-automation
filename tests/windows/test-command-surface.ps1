$ErrorActionPreference = 'Stop'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "[FAIL] $Message"
    }
    Write-Output "[PASS] $Message"
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$bin = Join-Path $root 'windows\bin'
$python = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$originalPath = $env:PATH
$originalHome = $env:JL_MIXING_HOME
$originalPython = $env:JL_MIXING_PYTHON
$originalRoot = $env:JL_MIXING_ROOT
$originalLocation = Get-Location
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("jl-mixing-windows-command-{0}" -f [Guid]::NewGuid().ToString('N'))

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $env:JL_MIXING_HOME = $root
    $env:JL_MIXING_PYTHON = $python
    $env:PATH = "$bin;$originalPath"

    $humanCommands = @(
        'new-studio',
        'new-client',
        'new-mix',
        'validate-intake',
        'new-revision',
        'approve-mix',
        'create-delivery'
    )
    foreach ($command in $humanCommands) {
        $output = & (Join-Path $bin "$command.cmd") --help 2>&1 | Out-String
        Assert-True ($LASTEXITCODE -eq 0) "$command launcher preserves help success"
        Assert-True ($output -match 'Usage:') "$command launcher returns human help"
    }

    $systemInfoText = & (Join-Path $bin 'jl-mixing.cmd') system-info --json 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'jl-mixing launcher preserves system-info success'
    $systemInfo = $systemInfoText | ConvertFrom-Json
    Assert-True ($systemInfo.api_version -eq '1.0') 'jl-mixing launcher reports API 1.0'
    Assert-True ($systemInfo.application.name -eq 'jl-mixing') 'jl-mixing launcher reports application identity'

    $workspace = Join-Path $tempRoot 'Windows Studio'
    & (Join-Path $bin 'new-studio.cmd') --root $workspace --name 'Windows Studio' --no-default-cd | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'Windows launcher creates studio'
    Assert-True (Test-Path -LiteralPath (Join-Path $workspace 'Studio\studio.json') -PathType Leaf) 'Windows studio configuration exists'

    $env:JL_MIXING_ROOT = $workspace
    . (Join-Path $bin 'jl-mixing-shell-integration.ps1')
    Set-Location -LiteralPath $tempRoot

    $enteredOutput = new-client windows-client --name 'Windows Client' --cd 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'PowerShell integration preserves successful new-client status'
    $expectedClient = [IO.Path]::GetFullPath((Join-Path $workspace 'Clients\Windows Client'))
    Assert-True ([string]::Equals((Get-Location).Path, $expectedClient, [StringComparison]::OrdinalIgnoreCase)) 'PowerShell integration changes parent location'
    Assert-True ($enteredOutput -match 'Entered:') 'PowerShell integration reports entered directory'

    Set-Location -LiteralPath $tempRoot
    new-client second-client --name 'Second Client' --no-cd | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) 'PowerShell integration preserves no-cd success'
    Assert-True ([string]::Equals((Get-Location).Path, $tempRoot, [StringComparison]::OrdinalIgnoreCase)) 'no-cd leaves parent location unchanged'

    $failureOutput = new-client BAD-ID 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -eq 5) 'PowerShell integration preserves validation exit code'
    Assert-True ([string]::Equals((Get-Location).Path, $tempRoot, [StringComparison]::OrdinalIgnoreCase)) 'failed creation leaves parent location unchanged'
    Assert-True ($failureOutput -match 'Error:') 'failed creation keeps human diagnostic'

    # The final product assertion intentionally observes a nonzero child exit.
    # Reset the harness status after validating it so a fully passing script
    # itself exits successfully under GitHub Actions.
    $global:LASTEXITCODE = 0
    Write-Output '[OK] Windows command surface'
} finally {
    Set-Location -LiteralPath $originalLocation
    $env:PATH = $originalPath
    if ($null -eq $originalHome) { Remove-Item Env:JL_MIXING_HOME -ErrorAction SilentlyContinue } else { $env:JL_MIXING_HOME = $originalHome }
    if ($null -eq $originalPython) { Remove-Item Env:JL_MIXING_PYTHON -ErrorAction SilentlyContinue } else { $env:JL_MIXING_PYTHON = $originalPython }
    if ($null -eq $originalRoot) { Remove-Item Env:JL_MIXING_ROOT -ErrorAction SilentlyContinue } else { $env:JL_MIXING_ROOT = $originalRoot }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
