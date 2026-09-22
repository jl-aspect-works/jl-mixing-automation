[CmdletBinding()]
param(
    [string]$Prefix
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

function Remove-ManagedProfileBlock([string]$Text) {
    $begin = '# >>> JL Mixing managed configuration >>>'
    $end = '# <<< JL Mixing managed configuration <<<'
    $start = $Text.IndexOf($begin, [StringComparison]::Ordinal)
    if ($start -lt 0) { return $Text }
    $finish = $Text.IndexOf($end, $start, [StringComparison]::Ordinal)
    if ($finish -lt 0) { throw 'PowerShell profile contains an incomplete JL Mixing managed block.' }
    $finish += $end.Length
    while ($finish -lt $Text.Length -and ($Text[$finish] -eq "`r" -or $Text[$finish] -eq "`n")) { $finish++ }
    $before = $Text.Substring(0, $start).TrimEnd("`r", "`n")
    $after = $Text.Substring($finish).TrimStart("`r", "`n")
    if ($before.Length -gt 0 -and $after.Length -gt 0) { return "$before`r`n$after" }
    return $before + $after
}

if ([string]::IsNullOrWhiteSpace($Prefix)) { $Prefix = Get-DefaultPrefix }
$Prefix = [IO.Path]::GetFullPath($Prefix)
$AppDir = Join-Path $Prefix 'share\jl-mixing'
$BinDir = Join-Path $Prefix 'bin'
$StateFile = Join-Path $AppDir 'install-state.json'

$state = $null
if (Test-Path -LiteralPath $StateFile -PathType Leaf) {
    try { $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } catch { Fail 'install-state.json is invalid; refusing unsafe uninstall.' 5 }
}

$publicCommands = @('jl-mixing','new-studio','new-client','new-mix','validate-intake','new-revision','approve-mix','create-delivery')
foreach ($command in $publicCommands) {
    $path = Join-Path $BinDir "$command.cmd"
    if (Test-Path -LiteralPath $path) {
        if (-not (Test-ManagedLauncher $path)) { Fail "refusing to remove unmanaged command: $path" 5 }
        Remove-Item -LiteralPath $path -Force
    }
}

$integration = Join-Path $BinDir 'jl-mixing-shell-integration.ps1'
if (Test-Path -LiteralPath $integration -PathType Leaf) {
    $text = Get-Content -LiteralPath $integration -Raw
    if ($text -notmatch 'JL Mixing Automation managed PowerShell integration') {
        Fail "refusing to remove unmanaged shell integration: $integration" 5
    }
    Remove-Item -LiteralPath $integration -Force
}

if ($null -ne $state -and $state.shell_integration.enabled -eq $true -and -not [string]::IsNullOrWhiteSpace([string]$state.shell_integration.profile)) {
    $profilePath = [IO.Path]::GetFullPath([string]$state.shell_integration.profile)
    if (Test-Path -LiteralPath $profilePath -PathType Leaf) {
        $original = Get-Content -LiteralPath $profilePath -Raw
        $clean = Remove-ManagedProfileBlock $original
        if ($state.shell_integration.profile_created -eq $true -and [string]::IsNullOrWhiteSpace($clean)) {
            Remove-Item -LiteralPath $profilePath -Force
        } else {
            Set-Content -LiteralPath $profilePath -Value $clean -NoNewline -Encoding utf8
        }
    }
}

if (Test-Path -LiteralPath $AppDir) {
    Remove-Item -LiteralPath $AppDir -Recurse -Force
}

foreach ($directory in @((Join-Path $Prefix 'share'), $BinDir, $Prefix)) {
    if (Test-Path -LiteralPath $directory -PathType Container) {
        $remaining = @(Get-ChildItem -LiteralPath $directory -Force)
        if ($remaining.Count -eq 0) { Remove-Item -LiteralPath $directory -Force }
    }
}

Write-Output 'JL Mixing Automation uninstalled.'
Write-Output 'Studio workspaces were not modified.'
