[CmdletBinding()]
param(
    [string]$OutputDir = 'dist'
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message, [int]$Code = 1) {
    [Console]::Error.WriteLine("Error: $Message")
    exit $Code
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = if ([IO.Path]::IsPathRooted($OutputDir)) {
    [IO.Path]::GetFullPath($OutputDir)
} else {
    [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDir))
}

$versionPath = Join-Path $root 'VERSION'
if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) { Fail 'VERSION is missing.' 3 }
$version = (Get-Content -LiteralPath $versionPath -Raw).Trim()
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    Fail "invalid VERSION: $version" 3
}

$runtime = Join-Path $root 'runtime\python.exe'
if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
    Fail 'runtime\python.exe is missing; run windows\build-runtime.ps1 first.' 3
}

$packageName = "jl-mixing-$version"
$archive = Join-Path $output "$packageName-windows.zip"
$checksum = "$archive.sha256"
$inventory = "$archive.inventory.txt"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("jl-mixing-release-{0}" -f [Guid]::NewGuid().ToString('N'))
$packageRoot = Join-Path $tempRoot $packageName

try {
    New-Item -ItemType Directory -Force -Path $output, $packageRoot | Out-Null

    foreach ($file in @('VERSION','API_VERSION','LICENSE','CHANGELOG.md')) {
        $source = Join-Path $root $file
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Fail "release source is missing $file" 3 }
        Copy-Item -LiteralPath $source -Destination $packageRoot
    }
    Copy-Item -LiteralPath (Join-Path $root 'packaging\RELEASE_README.md') -Destination (Join-Path $packageRoot 'README.md')

    foreach ($directory in @('src','api','schemas','templates','docs','windows','runtime')) {
        $source = Join-Path $root $directory
        if (-not (Test-Path -LiteralPath $source -PathType Container)) { Fail "release source is missing $directory" 3 }
        Copy-Item -LiteralPath $source -Destination (Join-Path $packageRoot $directory) -Recurse
    }

    $manifestEntries = Get-ChildItem -LiteralPath $packageRoot -File -Recurse |
        ForEach-Object {
            [IO.Path]::GetRelativePath($packageRoot, $_.FullName).Replace('\','/')
        } |
        Sort-Object -CaseSensitive
    $manifestEntries | Set-Content -LiteralPath (Join-Path $packageRoot 'RELEASE_MANIFEST.txt') -Encoding utf8

    Remove-Item -LiteralPath $archive, $checksum, $inventory -Force -ErrorAction SilentlyContinue
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $archive -CompressionLevel Optimal

    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($archive))" | Set-Content -LiteralPath $checksum -Encoding ascii

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $entries = $zip.Entries | ForEach-Object { $_.FullName } | Sort-Object -CaseSensitive
        $entries | Set-Content -LiteralPath $inventory -Encoding utf8
    } finally {
        $zip.Dispose()
    }

    if (-not (Select-String -LiteralPath $inventory -SimpleMatch "$packageName/runtime/python.exe" -Quiet)) {
        Fail 'release archive inventory does not contain runtime/python.exe.' 3
    }
    if (-not (Select-String -LiteralPath $inventory -SimpleMatch "$packageName/windows/install.ps1" -Quiet)) {
        Fail 'release archive inventory does not contain windows/install.ps1.' 3
    }

    Write-Output "Created release archive: $archive"
    Write-Output "Checksum: $checksum"
    Write-Output "Inventory: $inventory"
} finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
