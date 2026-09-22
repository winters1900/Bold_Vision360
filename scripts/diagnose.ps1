$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
Write-Output '=== Bold Vision 360 diagnostics ==='
Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match 'VID_2E1A'} | Select-Object Status,FriendlyName
Get-Process bold_capture,RealTimeStitcherSDKTest,CameraSDKDemo -ErrorAction SilentlyContinue | Select-Object Id,ProcessName
& .\.venv\Scripts\python.exe -c "import sys,onnxruntime,av,sounddevice;print(sys.version);print('ONNX providers:',onnxruntime.get_available_providers());print('FFmpeg libraries:',av.library_versions);print(sounddevice.query_devices())"
$cfgFile=if(Test-Path config.local.json){'config.local.json'}else{'config.example.json'}
$cfg=Get-Content $cfgFile -Raw | ConvertFrom-Json
try {Invoke-RestMethod "http://127.0.0.1:$($cfg.port)/api/status" | ConvertTo-Json -Depth 8} catch {Write-Output 'Service is not running'}
if(Test-Path runtime/capture.log){Get-Content runtime/capture.log -Tail 25}
