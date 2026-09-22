[CmdletBinding()]
param(
    [string]$Prefix,
    [switch]$NoShellIntegration
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message, [int]$Code = 1) {
    [Console]::Error.WriteLine("Error: $Message")
    exit $Code
}

function Get-DefaultPrefix {
    if (-not [string]::IsNullOrWhiteSpace($env:JL_MIXING_INSTALL_PREFIX)) {
        return $env:JL_MIXING_INSTALL_PREFIX
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Fail 'LOCALAPPDATA is not available; supply -Prefix explicitly.' 3
    }
    return (Join-Path $env:LOCALAPPDATA 'Programs\JL Mixing')
}

function Test-ManagedLauncher([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    return ((Get-Content -LiteralPath $Path -Raw) -match 'JL Mixing Automation managed Windows launcher')
}

function Get-ProfileTarget {
    if (-not [string]::IsNullOrWhiteSpace($env:JL_MIXING_TEST_PROFILE)) {
        return [IO.Path]::GetFullPath($env:JL_MIXING_TEST_PROFILE)
    }
    return [IO.Path]::GetFullPath($PROFILE.CurrentUserAllHosts)
}

function Remove-ManagedProfileBlock([string]$Text) {
    $begin = '# >>> JL Mixing managed configuration >>>'
    $end = '# <<< JL Mixing managed configuration <<<'
    $start = $Text.IndexOf($begin, [StringComparison]::Ordinal)
    if ($start -lt 0) { return $Text }
    $finish = $Text.IndexOf($end, $start, [StringComparison]::Ordinal)
    if ($finish -lt 0) { throw 'PowerShell profile contains an incomplete JL Mixing managed block.' }
    $finish += $end.Length
    while ($finish -lt $Text.Length -and ($Text[$finish] -eq "`r" -or $Text[$finish] -eq "`n")) { $finish++ }
    return ($Text.Remove($start, $finish - $start)).TrimEnd("`r", "`n") + $(if ($start -gt 0) { "`r`n" } else { '' })
}

function New-ManagedProfileText([string]$Existing, [string]$BinDir) {
    $clean = Remove-ManagedProfileBlock $Existing
    if ($clean.Length -gt 0 -and -not $clean.EndsWith("`n")) { $clean += "`r`n" }
    $escaped = $BinDir.Replace("'", "''")
    $block = @"
# >>> JL Mixing managed configuration >>>
`$jlMixingBin = '$escaped'
if (-not ((`$env:PATH -split ';') -contains `$jlMixingBin)) {
    `$env:PATH = "`$jlMixingBin;`$env:PATH"
}
`$jlMixingIntegration = Join-Path `$jlMixingBin 'jl-mixing-shell-integration.ps1'
if (Test-Path -LiteralPath `$jlMixingIntegration -PathType Leaf) {
    . `$jlMixingIntegration
}
# <<< JL Mixing managed configuration <<<
"@
    return $clean + $block
}

function Maybe-Fail([string]$Point) {
    if ($env:JL_MIXING_TEST_FAIL_INSTALL_AT -eq $Point) {
        throw "injected installation failure at $Point"
    }
}

if ([string]::IsNullOrWhiteSpace($Prefix)) { $Prefix = Get-DefaultPrefix }
$Prefix = [IO.Path]::GetFullPath($Prefix)
$SourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$AppDir = Join-Path $Prefix 'share\jl-mixing'
$BinDir = Join-Path $Prefix 'bin'
$ProfilePath = Get-ProfileTarget

$required = @('VERSION','API_VERSION','LICENSE','README.md','CHANGELOG.md','src','api','schemas','templates','docs','windows\bin')
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $relative))) {
        Fail "installation package is missing $relative" 3
    }
}

$bundledPython = Join-Path $SourceRoot 'runtime\python.exe'
$testPython = $env:JL_MIXING_TEST_PYTHON
$usingTestRuntime = $false
if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
    $runtimeSource = Join-Path $SourceRoot 'runtime'
} elseif (-not [string]::IsNullOrWhiteSpace($testPython) -and (Test-Path -LiteralPath $testPython -PathType Leaf)) {
    $usingTestRuntime = $true
    $runtimeSource = $null
    $testPython = [IO.Path]::GetFullPath($testPython)
} else {
    Fail 'installation package does not contain runtime\python.exe.' 3
}

$publicCommands = @('jl-mixing','new-studio','new-client','new-mix','validate-intake','new-revision','approve-mix','create-delivery')
New-Item -ItemType Directory -Force -Path $Prefix, $BinDir | Out-Null
foreach ($command in $publicCommands) {
    $destination = Join-Path $BinDir "$command.cmd"
    if ((Test-Path -LiteralPath $destination) -and -not (Test-ManagedLauncher $destination)) {
        Fail "refusing to overwrite unmanaged command: $destination" 5
    }
}

$integrationDestination = Join-Path $BinDir 'jl-mixing-shell-integration.ps1'
if ((Test-Path -LiteralPath $integrationDestination) -and ((Get-Content -LiteralPath $integrationDestination -Raw) -notmatch 'JL Mixing Automation managed PowerShell integration')) {
    Fail "refusing to overwrite unmanaged shell integration: $integrationDestination" 5
}

$stageRoot = Join-Path $Prefix ('.jl-mixing-install-stage-' + [Guid]::NewGuid().ToString('N'))
$backupRoot = Join-Path $Prefix ('.jl-mixing-install-backup-' + [Guid]::NewGuid().ToString('N'))
$stageApp = Join-Path $stageRoot 'share\jl-mixing'
$stageBin = Join-Path $stageRoot 'bin'
$profileExisted = Test-Path -LiteralPath $ProfilePath -PathType Leaf
$profileOriginal = if ($profileExisted) { Get-Content -LiteralPath $ProfilePath -Raw } else { '' }
$commitStarted = $false

try {
    New-Item -ItemType Directory -Force -Path $stageApp, $stageBin | Out-Null
    foreach ($file in @('VERSION','API_VERSION','LICENSE','README.md','CHANGELOG.md')) {
        Copy-Item -LiteralPath (Join-Path $SourceRoot $file) -Destination $stageApp
    }
    foreach ($directory in @('src','api','schemas','templates','docs','windows')) {
        Copy-Item -LiteralPath (Join-Path $SourceRoot $directory) -Destination $stageApp -Recurse
    }
    if (-not $usingTestRuntime) {
        Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $stageApp 'runtime') -Recurse
    }

    foreach ($command in $publicCommands) {
        $launcher = Join-Path $stageBin "$command.cmd"
        $pythonLine = if ($usingTestRuntime) {
            'set "JL_MIXING_PYTHON=' + $testPython + '"'
        } else {
            'set "JL_MIXING_PYTHON=%JL_MIXING_HOME%\runtime\python.exe"'
        }
        @"
@echo off
rem JL Mixing Automation managed Windows launcher. Generated by windows\install.ps1.
setlocal
for %%I in ("%~dp0..\share\jl-mixing") do set "JL_MIXING_HOME=%%~fI"
$pythonLine
call "%JL_MIXING_HOME%\windows\bin\$command.cmd" %*
exit /b %ERRORLEVEL%
"@ | Set-Content -LiteralPath $launcher -Encoding ascii
    }
    Copy-Item -LiteralPath (Join-Path $SourceRoot 'windows\bin\jl-mixing-shell-integration.ps1') -Destination $stageBin

    $state = [ordered]@{
        installation_prefix = $Prefix
        shell_integration = [ordered]@{
            enabled = -not $NoShellIntegration.IsPresent
            profile = if ($NoShellIntegration) { '' } else { $ProfilePath }
            profile_created = (-not $profileExisted)
        }
        test_runtime = $usingTestRuntime
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stageApp 'install-state.json') -Encoding utf8

    if (-not (Test-Path -LiteralPath (Join-Path $stageApp 'src\jl_mixing\__init__.py') -PathType Leaf)) { throw 'staged Python package is incomplete' }
    foreach ($command in $publicCommands) {
        if (-not (Test-Path -LiteralPath (Join-Path $stageBin "$command.cmd") -PathType Leaf)) { throw "staged launcher missing: $command" }
    }

    $stagedProfile = $null
    if (-not $NoShellIntegration) {
        $stagedProfile = New-ManagedProfileText $profileOriginal $BinDir
    }

    New-Item -ItemType Directory -Force -Path $backupRoot, (Join-Path $backupRoot 'bin') | Out-Null
    if (Test-Path -LiteralPath $AppDir) { Move-Item -LiteralPath $AppDir -Destination (Join-Path $backupRoot 'app') }
    foreach ($command in $publicCommands) {
        $existing = Join-Path $BinDir "$command.cmd"
        if (Test-Path -LiteralPath $existing -PathType Leaf) { Copy-Item -LiteralPath $existing -Destination (Join-Path $backupRoot 'bin') }
    }
    if (Test-Path -LiteralPath $integrationDestination -PathType Leaf) { Copy-Item -LiteralPath $integrationDestination -Destination (Join-Path $backupRoot 'bin') }
    if ($profileExisted) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent (Join-Path $backupRoot 'profile')) | Out-Null
        Set-Content -LiteralPath (Join-Path $backupRoot 'profile') -Value $profileOriginal -NoNewline -Encoding utf8
    }
    $commitStarted = $true

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $AppDir), $BinDir | Out-Null
    Move-Item -LiteralPath $stageApp -Destination $AppDir
    Maybe-Fail 'after-application'
    foreach ($command in $publicCommands) {
        Copy-Item -LiteralPath (Join-Path $stageBin "$command.cmd") -Destination (Join-Path $BinDir "$command.cmd") -Force
    }
    Copy-Item -LiteralPath (Join-Path $stageBin 'jl-mixing-shell-integration.ps1') -Destination $integrationDestination -Force
    Maybe-Fail 'after-launchers'

    if (-not $NoShellIntegration) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProfilePath) | Out-Null
        Set-Content -LiteralPath $ProfilePath -Value $stagedProfile -NoNewline -Encoding utf8
    }
    Maybe-Fail 'after-profile'

    if (-not (Test-Path -LiteralPath (Join-Path $AppDir 'VERSION') -PathType Leaf)) { throw 'installed application verification failed' }
    if (-not $usingTestRuntime -and -not (Test-Path -LiteralPath (Join-Path $AppDir 'runtime\python.exe') -PathType Leaf)) { throw 'installed runtime verification failed' }

    Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    $commitStarted = $false
} catch {
    $failure = $_
    if ($commitStarted) {
        Remove-Item -LiteralPath $AppDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath (Join-Path $backupRoot 'app') -PathType Container) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $AppDir) | Out-Null
            Move-Item -LiteralPath (Join-Path $backupRoot 'app') -Destination $AppDir
        }
        foreach ($command in $publicCommands) {
            $destination = Join-Path $BinDir "$command.cmd"
            Remove-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue
            $backup = Join-Path $backupRoot "bin\$command.cmd"
            if (Test-Path -LiteralPath $backup -PathType Leaf) { Copy-Item -LiteralPath $backup -Destination $destination }
        }
        Remove-Item -LiteralPath $integrationDestination -Force -ErrorAction SilentlyContinue
        $integrationBackup = Join-Path $backupRoot 'bin\jl-mixing-shell-integration.ps1'
        if (Test-Path -LiteralPath $integrationBackup -PathType Leaf) { Copy-Item -LiteralPath $integrationBackup -Destination $integrationDestination }
        if (-not $NoShellIntegration) {
            if ($profileExisted) {
                Set-Content -LiteralPath $ProfilePath -Value $profileOriginal -NoNewline -Encoding utf8
            } else {
                Remove-Item -LiteralPath $ProfilePath -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $backupRoot -Recurse -Force -ErrorAction SilentlyContinue
    [Console]::Error.WriteLine("Installation failed; previous installation restored.")
    [Console]::Error.WriteLine("Error: $($failure.Exception.Message)")
    exit 1
}

$version = (Get-Content -LiteralPath (Join-Path $AppDir 'VERSION') -Raw).Trim()
Write-Output "Installed JL Mixing Automation $version"
Write-Output "Application: $AppDir"
Write-Output "Commands:    $BinDir"
if ($NoShellIntegration) {
    Write-Output 'PowerShell profile: not modified (-NoShellIntegration)'
} else {
    Write-Output "PowerShell profile: $ProfilePath"
    Write-Output 'Open a new PowerShell session to activate JL Mixing shell integration.'
}
