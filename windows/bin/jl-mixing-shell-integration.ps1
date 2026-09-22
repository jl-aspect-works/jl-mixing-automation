# JL Mixing Automation managed PowerShell integration.
# Dot-source this file so creation commands can change the current PowerShell location.

if ($MyInvocation.InvocationName -ne '.') {
    [Console]::Error.WriteLine('This file must be dot-sourced by PowerShell.')
    [Console]::Error.WriteLine('Run: . (Get-Command jl-mixing-shell-integration.ps1).Source')
    exit 2
}

$env:JL_MIXING_SHELL_INTEGRATION = '1'

function Test-JLMixingAbsoluteWindowsPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Path -match '^[A-Za-z]:[\\/]') {
        return $true
    }
    if ($Path -match '^\\\\[^\\]+\\[^\\]+') {
        return $true
    }
    return $false
}

function Invoke-JLMixingCreationCommand {
    param(
        [Parameter(Mandatory = $true)][string]$CommandName,
        [Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArguments
    )

    $native = Get-Command "$CommandName.cmd" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $native) {
        [Console]::Error.WriteLine("Error: JL Mixing command was not found: $CommandName")
        $global:LASTEXITCODE = 1
        return
    }

    $resultFile = Join-Path ([IO.Path]::GetTempPath()) ("jl-mixing-cd-{0}.tmp" -f [Guid]::NewGuid().ToString('N'))
    try {
        $stream = [IO.File]::Open($resultFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Dispose()
    } catch {
        [Console]::Error.WriteLine('Error: unable to create secure JL Mixing shell result file.')
        $global:LASTEXITCODE = 1
        return
    }

    $hadPriorResult = Test-Path Env:JL_MIXING_CD_RESULT_FILE
    $priorResult = $env:JL_MIXING_CD_RESULT_FILE
    try {
        $env:JL_MIXING_CD_RESULT_FILE = $resultFile
        & $native.Source @CommandArguments
        $status = $LASTEXITCODE
    } finally {
        if ($hadPriorResult) {
            $env:JL_MIXING_CD_RESULT_FILE = $priorResult
        } else {
            Remove-Item Env:JL_MIXING_CD_RESULT_FILE -ErrorAction SilentlyContinue
        }
    }

    if ($status -ne 0) {
        Remove-Item -LiteralPath $resultFile -Force -ErrorAction SilentlyContinue
        $global:LASTEXITCODE = $status
        return
    }

    try {
        $lines = [IO.File]::ReadAllLines($resultFile)
    } catch {
        [Console]::Error.WriteLine('Error: creation succeeded, but JL Mixing could not read the directory result.')
        Remove-Item -LiteralPath $resultFile -Force -ErrorAction SilentlyContinue
        $global:LASTEXITCODE = 1
        return
    }
    Remove-Item -LiteralPath $resultFile -Force -ErrorAction SilentlyContinue

    if ($lines.Count -eq 0) {
        $global:LASTEXITCODE = 0
        return
    }
    if ($lines.Count -ne 1) {
        [Console]::Error.WriteLine('Error: creation succeeded, but JL Mixing returned an invalid directory result.')
        $global:LASTEXITCODE = 1
        return
    }

    $destination = $lines[0]
    if (-not (Test-JLMixingAbsoluteWindowsPath -Path $destination)) {
        [Console]::Error.WriteLine('Error: creation succeeded, but JL Mixing returned a non-absolute directory.')
        $global:LASTEXITCODE = 1
        return
    }
    if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
        [Console]::Error.WriteLine("Error: creation succeeded, but the requested directory does not exist: $destination")
        $global:LASTEXITCODE = 1
        return
    }

    try {
        Set-Location -LiteralPath $destination -ErrorAction Stop
    } catch {
        [Console]::Error.WriteLine("Error: creation succeeded, but PowerShell could not enter: $destination")
        $global:LASTEXITCODE = 1
        return
    }

    Write-Output "Entered: $destination"
    $global:LASTEXITCODE = 0
}

function new-client {
    Invoke-JLMixingCreationCommand -CommandName 'new-client' @args
}

function new-mix {
    Invoke-JLMixingCreationCommand -CommandName 'new-mix' @args
}

function new-revision {
    Invoke-JLMixingCreationCommand -CommandName 'new-revision' @args
}
