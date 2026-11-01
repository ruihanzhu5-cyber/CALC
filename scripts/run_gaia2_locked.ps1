param([Parameter(Mandatory=$true)][string]$Config,
      [string]$Distro = 'CALC-Research')
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
if (-not $configPath.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Config must be on D:.' }
$cfg = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
if (-not $cfg.output_dir.StartsWith('/mnt/d/CALC-experiments/runs/')) { throw 'Expected D: experiment output directory.' }
$runDir = 'D:\' + $cfg.output_dir.Substring(7).Replace('/', '\')
$receiptPath = Join-Path $runDir 'launch_receipt.json'
if (Test-Path -LiteralPath (Join-Path $runDir 'execute_queue.json')) { throw 'Existing paid queue; no automatic restart.' }
$credential = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
if ($credential) { $env:DEEPSEEK_API_KEY = $credential }
if (-not $env:DEEPSEEK_API_KEY) { throw 'DEEPSEEK_API_KEY unavailable to scheduled task.' }
$credential = $null
$env:WSLENV = (($env:WSLENV -split ':' | Where-Object { $_ -and $_ -notmatch '^DEEPSEEK_API_KEY(/.*)?$' }) + 'DEEPSEEK_API_KEY') -join ':'
$repo = Split-Path $PSScriptRoot -Parent
$linuxScript = '/mnt/d/' + (Join-Path $repo 'scripts\run_gaia2_locked.sh').Substring(3).Replace('\', '/')
$linuxConfig = '/mnt/d/' + $configPath.Substring(3).Replace('\', '/')
$receipt = [ordered]@{status='starting'; host_pid=$PID; started_at=[DateTimeOffset]::Now.ToString('o');
    config=$configPath; run=$runDir; automatic_restart=$false; distro=$Distro;
    scope='Both methods once on every ID in this config task lock; no paid retry'}
$stream = [IO.File]::Open($receiptPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
$writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
try { $writer.Write(($receipt | ConvertTo-Json -Depth 5)) } finally { $writer.Dispose() }
function Save-Receipt { [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false)) }
try {
    & wsl.exe -d $Distro -- bash $linuxScript --config $linuxConfig --execute > (Join-Path $runDir 'batch.host.log') 2>&1
    $receipt.exit_code = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'Batch execution failed; inspect queue and case logs. No automatic retry.' }
    $receipt.status = 'finished'
    $receipt.finished_at = [DateTimeOffset]::Now.ToString('o')
    Save-Receipt
} catch {
    $receipt.status = 'failed'
    $receipt.error = $_.Exception.Message
    Save-Receipt
    throw
}
