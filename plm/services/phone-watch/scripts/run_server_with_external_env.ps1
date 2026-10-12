param(
  [string]$EnvFile = "C:\Users\JT\Desktop\备份\cst\phone_watch\python-sqlite-https-www-motorola-com\.env",
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RootDir

if (-not (Test-Path -LiteralPath $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

Get-Content -LiteralPath $EnvFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
    return
  }
  $parts = $line.Split("=", 2)
  $name = $parts[0].Trim()
  $value = $parts[1].Trim().Trim('"').Trim("'")
  [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

py -m phone_watch serve --host $HostName --port $Port
