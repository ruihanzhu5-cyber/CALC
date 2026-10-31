param(
    [string]$ExperimentRoot='D:\CALC-experiments',
    [string]$RunTag='dev5-native-retry19-v2'
)
$ErrorActionPreference='Stop'
$repo=Join-Path $ExperimentRoot 'code\CALC'
$run=Join-Path (Join-Path $ExperimentRoot 'runs') $RunTag
$python=Join-Path $ExperimentRoot 'envs\calc-win\Scripts\python.exe'
$manifest=Get-Content -Raw -LiteralPath "$run\retry_manifest.json"|ConvertFrom-Json
$status=[ordered]@{run_tag=$RunTag;kind='missing_submission_retry';expected_tasks=$manifest.retry_count;retained_tasks=$manifest.retained_count;methods=[ordered]@{}}
foreach($method in @('main','porchestra','clm','dynaflow','joint')){$status.methods[$method]='waiting_for_actor_tasks'}
function Save-Status {
    $status['updated_at']=[DateTimeOffset]::Now.ToOffset([TimeSpan]::FromHours(8)).ToString('o')
    $status|ConvertTo-Json -Depth 8|Set-Content -LiteralPath "$run\judging_status.json" -Encoding utf8
}
Save-Status
foreach($method in @('main','porchestra','clm','dynaflow','joint')){
    $ids=@($manifest.retry|Where-Object method -eq $method|ForEach-Object{$_.query_id})
    if($ids.Count -eq 0){$status.methods[$method]='no_retries';Save-Status;continue}
    while($true){
        if(-not (Test-Path -LiteralPath "$run\queue.json")){Start-Sleep -Seconds 5;continue}
        $queue=Get-Content -Raw -LiteralPath "$run\queue.json"|ConvertFrom-Json
        $states=@($ids|ForEach-Object{$job=$queue.jobs.PSObject.Properties["$method/$_"];if($null -eq $job){'pending'}else{$job.Value.status}})
        if($queue.status -in @('interrupted','stopped_by_user','actor_process_error') -or @($states|Where-Object{$_ -in @('process_error','interrupted','interrupted_by_user')}).Count -gt 0){
            $status['status']='blocked_or_stopped_actor';Save-Status;exit 1
        }
        if(@($states|Where-Object{$_ -ne 'process_completed'}).Count -eq 0){break}
        Start-Sleep -Seconds 10
    }
    $status.methods[$method]='exporting';Save-Status
    $exportArgs=@((Join-Path $repo 'scripts\export_pilot.py'),'--root',$ExperimentRoot,'--run-tag',$RunTag,'--limit','5','--methods',$method)
    foreach($id in $ids){$exportArgs+=@('--query-id',"$id")}
    & $python @exportArgs
    if($LASTEXITCODE -ne 0){$status.methods[$method]='export_error';Save-Status;exit 1}
    $status.methods[$method]='judging';Save-Status
    & (Join-Path $repo 'scripts\invoke_qwen_judge.ps1') -JudgeArguments @(
        '--config',(Join-Path $repo 'configs\qwen_judge.siliconflow.json'),
        '--input-dir',"$run\official\$method",'--ground-truth',
        (Join-Path $ExperimentRoot 'bench\browsecomp-plus\scoring-only\reference830.judge-only.jsonl'),
        '--output-dir',"$run\evals\$method",'--execute')
    if($LASTEXITCODE -ne 0){$status.methods[$method]='judge_error';Save-Status;exit 1}
    $e=Get-Content -Raw -LiteralPath "$run\evals\$method\evaluation_summary.json"|ConvertFrom-Json
    if($e.evaluation -ne 'complete' -or $e.num_tasks -ne $ids.Count -or $e.num_judge_errors -ne 0){
        $status.methods[$method]='incomplete_evaluation';Save-Status;exit 1
    }
    $status.methods[$method]='scored';Save-Status
}
$status['evaluation']='complete';Save-Status
