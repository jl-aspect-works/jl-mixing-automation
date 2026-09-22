$ErrorActionPreference = 'Stop'

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "[FAIL] $Message" }
    Write-Output "[PASS] $Message"
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$runtime = Join-Path $root 'runtime\python.exe'
$originalHome = $env:JL_MIXING_HOME
$originalPythonPath = $env:PYTHONPATH

try {
    Assert-True (Test-Path -LiteralPath $runtime -PathType Leaf) 'bundled Windows runtime executable exists'
    $env:JL_MIXING_HOME = $root
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    $systemInfoText = & $runtime -m jl_mixing.cli system-info --json 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'bundled runtime executes API dispatcher'
    $systemInfo = $systemInfoText | ConvertFrom-Json
    Assert-True ($systemInfo.api_version -eq '1.0') 'bundled runtime preserves API version'
    Assert-True ($systemInfo.application.name -eq 'jl-mixing') 'bundled runtime preserves application identity'

    $help = & $runtime -m jl_mixing.new_studio_cli --help 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -eq 0) 'bundled runtime executes human CLI module'
    Assert-True ($help -match 'Usage: new-studio') 'bundled runtime preserves human help output'

    $unsupported = & $runtime -m jl_mixing.not_a_command 2>&1 | Out-String
    Assert-True ($LASTEXITCODE -eq 2) 'bundled runtime rejects unsupported module with argument exit code'
    Assert-True ($unsupported -match 'unsupported JL Mixing runtime module') 'bundled runtime reports unsupported module'

    $global:LASTEXITCODE = 0
    Write-Output '[OK] Windows bundled runtime'
} finally {
    if ($null -eq $originalHome) { Remove-Item Env:JL_MIXING_HOME -ErrorAction SilentlyContinue } else { $env:JL_MIXING_HOME = $originalHome }
    if ($null -eq $originalPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $originalPythonPath }
}
