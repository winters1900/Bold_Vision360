param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
if(!(Test-Path '.venv\Scripts\python.exe')){throw 'Run scripts/setup.ps1 first.'}
if(!(Test-Path 'web/dist/index.html')){throw 'Run scripts/build.ps1 first.'}
$cfgFile=if(Test-Path config.local.json){'config.local.json'}else{'config.example.json'}
$cfg=Get-Content $cfgFile -Raw | ConvertFrom-Json
$url="http://127.0.0.1:$($cfg.port)"
try {$existing=Invoke-RestMethod "$url/api/status" -TimeoutSec 2} catch {$existing=$null}
if($existing){if(!$NoBrowser){Start-Process $url};Write-Host "Already running: $url";exit}
$env:TF_CPP_MIN_LOG_LEVEL='2'
$env:TF_ENABLE_ONEDNN_OPTS='0'
$pythonPath=Join-Path $projectRoot '.venv/Scripts/python.exe'
New-Item -ItemType Directory -Force runtime | Out-Null
$p=Start-Process -FilePath $pythonPath -ArgumentList "-m uvicorn server.app:app --host 127.0.0.1 --port $($cfg.port) --no-access-log" -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'runtime/service.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'runtime/service.stderr.log')
try {
  $ready=$false
  for($i=0;$i -lt 60;$i++){
    if($p.HasExited){throw 'Service exited. Run scripts/diagnose.ps1.'}
    try {$null=Invoke-RestMethod "$url/api/status" -TimeoutSec 1;$ready=$true;break} catch {Start-Sleep -Milliseconds 500}
  }
  if(!$ready){throw 'Service startup timed out. See runtime/service.stderr.log.'}
  if(!$NoBrowser){Start-Process $url}
  Write-Host "Bold Vision 360: $url - keep this terminal open; Ctrl+C stops the service."
  while(!$p.HasExited){Start-Sleep -Milliseconds 500}
} finally {
  try {Invoke-RestMethod "$url/api/stop" -Method Post -TimeoutSec 12 | Out-Null} catch {}
  if(!$p.HasExited){Stop-Process -Id $p.Id}
}
