param(
    [string]$ExperimentRoot = 'D:\CALC-experiments',
    [string]$RunTag = 'dev5-flash-1m-v0',
    [int]$Limit = 5
)
$ErrorActionPreference = 'Stop'
$repo = Join-Path $ExperimentRoot 'code\CALC'
$python = Join-Path $ExperimentRoot 'envs\calc-win\Scripts\python.exe'
$run = Join-Path (Join-Path $ExperimentRoot 'runs') $RunTag
$queuePath = Join-Path $run 'queue.json'
$statusPath = Join-Path $run 'judging_status.json'
$taskFile = Join-Path $ExperimentRoot 'bench\browsecomp-plus\tasks\first20.dev.jsonl'
$queries = @(Get-Content -LiteralPath $taskFile | Where-Object { $_.Trim() } |
    ForEach-Object { (ConvertFrom-Json $_).query_id } | Select-Object -First $Limit)
$methods = @('main','porchestra','clm','dynaflow','joint')
$status = [ordered]@{run_tag=$RunTag; scope='development_pilot'; query_ids=$queries; methods=[ordered]@{}}
foreach ($method in $methods) { $status.methods[$method] = 'waiting_for_actor_tasks' }
function Save-Status {
    $status['updated_at'] = [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(8)).ToString('o')
    $status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statusPath -Encoding utf8
}
Save-Status
foreach ($method in $methods) {
    while ($true) {
        $queue = Get-Content -Raw -LiteralPath $queuePath | ConvertFrom-Json
        if ($queue.status -in @('stopped_by_user','interrupted')) {
            $status['status']='stopped_with_actor_queue'; Save-Status
            exit 0
        }
        $states = @($queries | ForEach-Object {
            $property = $queue.jobs.PSObject.Properties["$method/$_"]
            if ($null -eq $property) { 'queued' } else { $property.Value.status }
        })
        if (@($states | Where-Object { $_ -in @('process_error','interrupted','interrupted_by_user') }).Count -gt 0) {
            $status.methods[$method] = 'blocked_actor_process_error'; Save-Status
            throw "Inspect failed actor process for $method before scoring."
        }
        if (@($states | Where-Object { $_ -ne 'process_completed' }).Count -eq 0) { break }
        Start-Sleep -Seconds 10
    }
    $status.methods[$method] = 'exporting_native_results'; Save-Status
    & $python (Join-Path $repo 'scripts\export_pilot.py') --root $ExperimentRoot --run-tag $RunTag --limit $Limit --methods $method
    if ($LASTEXITCODE -ne 0) { $status.methods[$method]='export_error'; Save-Status; exit $LASTEXITCODE }
    $inputDirectory = Join-Path $run "official\$method"
    $evaluationDirectory = Join-Path $run "evals\$method"
    $summaryPath = Join-Path $evaluationDirectory 'evaluation_summary.json'
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        $status.methods[$method] = 'judging'; Save-Status
        & (Join-Path $repo 'scripts\invoke_qwen_judge.ps1') -JudgeArguments @(
            '--config',(Join-Path $repo 'configs\qwen_judge.siliconflow.json'),
            '--input-dir',$inputDirectory,
            '--ground-truth',(Join-Path $ExperimentRoot 'bench\browsecomp-plus\scoring-only\reference830.judge-only.jsonl'),
            '--output-dir',$evaluationDirectory,'--execute')
        if ($LASTEXITCODE -ne 0) { $status.methods[$method]='judge_error'; Save-Status; exit $LASTEXITCODE }
    }
    $summary = Get-Content -Raw -LiteralPath $summaryPath | ConvertFrom-Json
    if ($summary.evaluation -ne 'complete' -or $summary.num_tasks -ne $Limit -or $summary.num_judge_errors -ne 0) {
        $status.methods[$method]='incomplete_evaluation'; Save-Status
        throw 'Evaluation does not cover the complete selected task set.'
    }
    $status.methods[$method] = 'scored'; Save-Status
}
& $python (Join-Path $repo 'scripts\export_pilot.py') --root $ExperimentRoot --run-tag $RunTag --limit $Limit
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$status['evaluation']='complete'; Save-Status
