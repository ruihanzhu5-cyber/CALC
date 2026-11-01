param(
    [string]$Destination = 'D:\CALC'
)
$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$targetRoot = [IO.Path]::GetFullPath($Destination)
if ($targetRoot -eq $sourceRoot -or $targetRoot.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'Choose a backup directory outside the source repository.'
}
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
# Copy tracked and unignored source files. Git exclusions cover secrets, dependencies and run data.
$files = @(git -C $sourceRoot ls-files --cached --others --exclude-standard) | Sort-Object -Unique
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate the source repository.' }
$hashes = @()
foreach ($file in $files) {
    $sourceFile = Join-Path $sourceRoot $file
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) { continue }
    $targetFile = Join-Path $targetRoot $file
    New-Item -ItemType Directory -Path (Split-Path $targetFile -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $targetFile -Force
    $sourceHash = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash
    if ($sourceHash -ne $targetHash) { throw "Backup hash mismatch: $file" }
    $hashes += [PSCustomObject]@{ path = $file; sha256 = $sourceHash }
}
$hashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $targetRoot 'BACKUP_SHA256.json') -Encoding utf8
$commit = git -C $sourceRoot rev-parse HEAD
$stamp = [DateTime]::UtcNow.AddHours(8).ToString('yyyy-MM-dd HH:mm:ss')
Set-Content -LiteralPath (Join-Path $targetRoot 'BACKUP_INFO.txt') -Encoding utf8 -Value @(
    "CALC code backup at $stamp Asia/Shanghai",
    "Source: $sourceRoot",
    "Source HEAD: $commit",
    'Includes working-tree source, documentation and configs. Excludes git metadata, dependencies, secrets, data and runs.'
)
Write-Output "Code backup ready: $targetRoot ($($hashes.Count) hash-verified files; HEAD $commit)"
exit 0
