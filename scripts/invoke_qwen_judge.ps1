[CmdletBinding(PositionalBinding=$false)]
param(
    [string]$SecretPath = 'D:\CALC-experiments\secrets\siliconflow-qwen.dpapi',
    [Parameter(ValueFromRemainingArguments=$true)] [string[]]$JudgeArguments
)
$ErrorActionPreference = 'Stop'
$previous = $env:BCP_JUDGE_API_KEY
try {
    $secure = (Get-Content -Raw -LiteralPath $SecretPath).Trim() | ConvertTo-SecureString
    $env:BCP_JUDGE_API_KEY = [Net.NetworkCredential]::new('', $secure).Password
    & 'D:\CALC-experiments\envs\calc-win\Scripts\python.exe' -m calc.evaluation.qwen_api @JudgeArguments
    $code = $LASTEXITCODE
} finally {
    $env:BCP_JUDGE_API_KEY = $previous
}
exit $code
