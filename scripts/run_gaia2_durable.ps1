$ErrorActionPreference = 'Stop'
$repo = 'D:\CALC-experiments\code\CALC-task-progress'
$run = 'D:\CALC-experiments\runs\gaia2-adaptability5-flash-v1'
$receiptPath = Join-Path $run 'launch_receipt.json'
if (Test-Path -LiteralPath $receiptPath) { throw 'Batch already launched; no automatic paid restart.' }
if (Test-Path -LiteralPath (Join-Path $run 'execute_queue.json')) { throw 'Existing execution queue.' }
$credential = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
if ($credential) { $env:DEEPSEEK_API_KEY = $credential }
if (-not $env:DEEPSEEK_API_KEY) { throw 'DEEPSEEK_API_KEY unavailable to scheduled task.' }
$credential = $null
$env:WSLENV = (($env:WSLENV -split ':' | Where-Object { $_ -and $_ -notmatch '^DEEPSEEK_API_KEY(/.*)?$' }) + 'DEEPSEEK_API_KEY') -join ':'
$receipt = [ordered]@{
    status = 'starting'; host_pid = $PID; started_at = [DateTimeOffset]::Now.ToString('o')
    run = $run; automatic_restart = $false; host = 'Windows Task Scheduler / CALC-Research WSL'
}
function Save-Receipt { $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8 }
Save-Receipt
try {
    & wsl.exe -d CALC-Research -- bash /mnt/d/CALC-experiments/code/CALC-task-progress/scripts/run_gaia2_batch.sh > (Join-Path $run 'batch.host.log') 2>&1
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
