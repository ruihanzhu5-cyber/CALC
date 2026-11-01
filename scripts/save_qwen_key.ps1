param([string]$SecretPath = 'D:\CALC-experiments\secrets\siliconflow-qwen.dpapi')
$ErrorActionPreference = 'Stop'
$secret = Read-Host 'Enter SiliconFlow Qwen API Key' -AsSecureString
$directory = Split-Path -Parent $SecretPath
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $identity.User, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
Set-Acl -LiteralPath $directory -AclObject $acl
$secret | ConvertFrom-SecureString | Set-Content -LiteralPath $SecretPath -Encoding utf8
Write-Output 'Qwen credential stored using Windows DPAPI; key is not printed.'
