param(
    [string]$RunTag='dev5-native-recovery19-v3',
    [string]$RecoveryRun='dev5-native-retry19-v2',
    [ValidateRange(1,100)][int]$EpisodeConcurrency=19,
    [ValidateRange(1,100)][int]$ModelConcurrency=32,
    [string]$OnlyTask=''
)
$ErrorActionPreference='Stop'
if($RunTag -notmatch '^[A-Za-z0-9_.-]+$' -or $RecoveryRun -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Invalid run tags'}
$repo='D:\CALC-experiments\code\CALC'
$run="D:\CALC-experiments\runs\$RunTag"
New-Item -ItemType Directory -Path $run -Force | Out-Null
if(Test-Path -LiteralPath "$run\launch_receipt.json"){throw 'This paid attempt was already launched; never auto-restart it'}
foreach($name in @('DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL')){
    $value=[Environment]::GetEnvironmentVariable($name,'User')
    if($value){[Environment]::SetEnvironmentVariable($name,$value,'Process')}
}
if(-not $env:DEEPSEEK_API_KEY){throw 'Provider credential unavailable to the user task'}
$env:CALC_NATIVE_SETTINGS='1';$env:CALC_MODEL_CONCURRENCY="$ModelConcurrency";$env:CALC_TOKEN_LIMIT='0';$env:CALC_SYSTEMD='1'
Set-Location $repo
$receipt=[ordered]@{run_tag=$RunTag;recovery_run=$RecoveryRun;only_task=$OnlyTask;episode_concurrency=$EpisodeConcurrency;model_concurrency=$ModelConcurrency;status='starting';host_pid=$PID;started_at=[DateTimeOffset]::Now.ToString('o');host='Windows Task Scheduler';automatic_paid_restart=$false}
function Save-Receipt {$receipt|ConvertTo-Json -Depth 5|Set-Content -LiteralPath "$run\launch_receipt.json" -Encoding utf8}
Save-Receipt
try{
    & "$repo\scripts\invoke_wsl_experiment.ps1" -StartGateway > "$run\gateway-start.log" 2>&1
    if($LASTEXITCODE -ne 0){throw 'Gateway startup failed; inspect gateway-start.log'}
    $receipt.status='setup_and_actor_running';Save-Receipt
    $pwsh=(Get-Process -Id $PID).Path
    $watcher=Start-Process -FilePath $pwsh -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-File',"$repo\scripts\watch_native_retries.ps1",'-RunTag',$RunTag) -RedirectStandardOutput "$run\judge-watcher.stdout.log" -RedirectStandardError "$run\judge-watcher.stderr.log"
    $receipt.watcher_pid=$watcher.Id;Save-Receipt
    $linuxArguments=@('bash','/mnt/d/CALC-experiments/code/CALC/scripts/run_recovered_native.sh',$RunTag,$RecoveryRun,"$EpisodeConcurrency")
    if($OnlyTask){$linuxArguments+=$OnlyTask}
    & "$repo\scripts\invoke_wsl_experiment.ps1" @linuxArguments > "$run\actor-host.log" 2>&1
    $receipt.actor_exit=$LASTEXITCODE
    if($LASTEXITCODE -ne 0){throw 'Execution stopped; inspect actor-host.log. No automatic paid retry.'}
    $receipt.status='actors_finished_waiting_for_judge';Save-Receipt
    $watcher.WaitForExit()
    $receipt.judge_exit=$watcher.ExitCode
    $receipt.status=if($watcher.ExitCode -eq 0){'complete'}else{'judge_error'}
    Save-Receipt
}catch{
    $receipt.status='interrupted_or_failed';$receipt.error=$_.Exception.Message;Save-Receipt
    if($watcher -and -not $watcher.HasExited){Stop-Process -Id $watcher.Id}
    $queuePath="$run\queue.json"
    if(Test-Path -LiteralPath $queuePath){
        $queue=Get-Content -Raw -LiteralPath $queuePath|ConvertFrom-Json
        $queue|Add-Member -NotePropertyName status -NotePropertyValue 'interrupted' -Force
        foreach($job in $queue.jobs.PSObject.Properties){if($job.Value.status -eq 'running'){$job.Value.status='interrupted'}}
        $queue|ConvertTo-Json -Depth 15|Set-Content -LiteralPath "$run\queue.host-interruption.json" -Encoding utf8
    }
    throw
}
