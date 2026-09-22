[CmdletBinding()]
param(
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $root 'runtime'
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)

$python = (Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1)
if ($null -eq $python) {
    throw 'Python is required to build the Windows runtime.'
}

& $python.Source -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller is not installed. Install packaging/windows-build-requirements.txt first.'
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("jl-mixing-pyinstaller-{0}" -f [Guid]::NewGuid().ToString('N'))
$dist = Join-Path $tempRoot 'dist'
$work = Join-Path $tempRoot 'work'
$spec = Join-Path $tempRoot 'spec'

try {
    New-Item -ItemType Directory -Force -Path $dist, $work, $spec | Out-Null
    & $python.Source -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --console `
        --name python `
        --paths (Join-Path $root 'src') `
        --distpath $dist `
        --workpath $work `
        --specpath $spec `
        (Join-Path $root 'windows\runtime_bootstrap.py')
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $built = Join-Path $dist 'python'
    if (-not (Test-Path -LiteralPath (Join-Path $built 'python.exe') -PathType Leaf)) {
        throw 'PyInstaller output is missing python.exe.'
    }

    if (Test-Path -LiteralPath $OutputDir) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputDir) | Out-Null
    Move-Item -LiteralPath $built -Destination $OutputDir
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output "Built JL Mixing Windows runtime: $OutputDir"
