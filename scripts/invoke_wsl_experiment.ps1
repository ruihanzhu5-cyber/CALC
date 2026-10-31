param(
    [switch]$StartGateway,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$LinuxCommand
)
$ErrorActionPreference = 'Stop'
if (-not $env:DEEPSEEK_API_KEY) { throw 'DEEPSEEK_API_KEY is not set in the Windows environment.' }
$utf8 = [Text.Encoding]::UTF8
$hmac = [Security.Cryptography.HMACSHA256]::new($utf8.GetBytes($env:DEEPSEEK_API_KEY))
try {
    $env:CALC_GATEWAY_KEY = [Convert]::ToHexString(
        $hmac.ComputeHash($utf8.GetBytes('CALC-local-model-gateway-v0-20261031'))).ToLowerInvariant()
} finally { $hmac.Dispose() }
$forward = @('CALC_GATEWAY_KEY')
if ($StartGateway) { $forward += @('DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL') }
$existing = @($env:WSLENV -split ':' | Where-Object { $_ -and $_ -notmatch '^(DEEPSEEK_API_KEY|DEEPSEEK_BASE_URL|CALC_GATEWAY_KEY)(/.*)?$' })
$env:WSLENV = ($existing + $forward) -join ':'
if ($StartGateway) {
    & wsl.exe -d CALC-Research -- bash /mnt/d/CALC-experiments/code/CALC/scripts/start_model_gateway.sh
} elseif ($LinuxCommand.Count) {
    & wsl.exe -d CALC-Research -- @LinuxCommand
} else {
    throw 'Supply -StartGateway or a Linux command to run.'
}
exit $LASTEXITCODE
