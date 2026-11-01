param([switch]$MantaRemaining4, [switch]$MantaFirstRetry)
$ErrorActionPreference = 'Stop'
if ($MantaRemaining4 -and $MantaFirstRetry) { throw 'Choose only one explicit scope.' }
$repo = 'D:\CALC-experiments\code\CALC-task-progress'
$run = 'D:\CALC-experiments\runs\gaia2-adaptability5-flash-v1'
$receiptName = if ($MantaFirstRetry) { 'manta_first_retry_launch_receipt.json' } elseif ($MantaRemaining4) { 'manta_remaining_launch_receipt.json' } else { 'launch_receipt.json' }
$queueName = if ($MantaRemaining4) { 'manta_remaining_queue.json' } else { 'execute_queue.json' }
$hostLog = if ($MantaFirstRetry) { 'manta_first_retry.host.log' } elseif ($MantaRemaining4) { 'manta_remaining.host.log' } else { 'batch.host.log' }
$receiptPath = Join-Path $run $receiptName
if (Test-Path -LiteralPath $receiptPath) { throw 'Batch already launched; no automatic paid restart.' }
$queueRoot = if ($MantaFirstRetry) { Join-Path $run 'manta-first-retry' } else { $run }
if (Test-Path -LiteralPath (Join-Path $queueRoot $queueName)) { throw 'Existing execution queue.' }
$credential = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
if ($credential) { $env:DEEPSEEK_API_KEY = $credential }
if (-not $env:DEEPSEEK_API_KEY) { throw 'DEEPSEEK_API_KEY unavailable to scheduled task.' }
$credential = $null
$env:WSLENV = (($env:WSLENV -split ':' | Where-Object { $_ -and $_ -notmatch '^DEEPSEEK_API_KEY(/.*)?$' }) + 'DEEPSEEK_API_KEY') -join ':'
$receipt = [ordered]@{
    status = 'starting'; host_pid = $PID; started_at = [DateTimeOffset]::Now.ToString('o')
    run = $run; automatic_restart = $false; host = 'Windows Task Scheduler / CALC-Research WSL'
    scope = $(if ($MantaFirstRetry) { 'User explicitly approved one retry of MANTA scenario_universe_29_aa11lh' } elseif ($MantaRemaining4) { 'Only four unattempted MANTA cases; first failed case NOT rerun' } else { 'All five cases, both methods' })
}
function Save-Receipt { $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8 }
Save-Receipt
try {
    $linuxArgs = @('bash', '/mnt/d/CALC-experiments/code/CALC-task-progress/scripts/run_gaia2_batch.sh')
    if ($MantaRemaining4) {
        $linuxArgs += @('--methods', 'manta', '--tasks', 'scenario_universe_22_h34zyy', 'scenario_universe_21_nc6nqf', 'scenario_universe_29_096dyu', 'scenario_universe_23_ekcbfh', '--queue-name', $queueName)
    }
    if ($MantaFirstRetry) {
        $linuxArgs += @('--config', '/mnt/d/CALC-experiments/runs/gaia2-adaptability5-flash-v1/manta-first-retry.config.json', '--methods', 'manta', '--tasks', 'scenario_universe_29_aa11lh')
    }
    & wsl.exe -d CALC-Research -- @linuxArgs > (Join-Path $run $hostLog) 2>&1
    $receipt.exit_code = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'GAIA2 batch stopped with an execution failure; inspect execute_queue.json and case logs.' }
    $receipt.status = 'finished'
    $receipt.finished_at = [DateTimeOffset]::Now.ToString('o')
    Save-Receipt
} catch {
    $receipt.status = 'failed'
    $receipt.error = $_.Exception.Message
    Save-Receipt
    throw
}
