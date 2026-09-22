param([string]$Python='python',[switch]$InstallCpp)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
New-Item -ItemType Directory -Force .tools,models,recordings,runtime | Out-Null
if(!(Test-Path config.local.json)){Copy-Item config.example.json config.local.json}
if($InstallCpp){
  $installer='C:\Program Files (x86)\Microsoft Visual Studio\Installer\setup.exe'
  $vswhere='C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
  if(!(Test-Path $vswhere)){throw 'Install Visual Studio 2022/2026 with Desktop development with C++ first.'}
  $vsPath=& $vswhere -latest -products '*' -property installationPath
  $p=Start-Process $installer -ArgumentList "modify --installPath `"$vsPath`" --add Microsoft.VisualStudio.Workload.NativeDesktop --includeRecommended --quiet --norestart" -Verb RunAs -WindowStyle Hidden -Wait -PassThru
  if($p.ExitCode -notin @(0,3010)){throw "Visual Studio installer failed: $($p.ExitCode)"}
}
if(!(Test-Path .venv/Scripts/python.exe)){
  & $Python -c "import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8, 'Python 3.12 x64 required'"
  if($LASTEXITCODE){throw 'Pass -Python with a Python 3.12 x64 executable path.'}
  & $Python -m venv .venv;if($LASTEXITCODE){throw 'Virtual environment creation failed'}
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if($LASTEXITCODE){throw 'Python dependencies failed'}
if(!(Test-Path .tools/node-v22.16.0-win-x64/node.exe)){
  Invoke-WebRequest 'https://nodejs.org/dist/v22.16.0/node-v22.16.0-win-x64.zip' -OutFile .tools/node.zip
  Expand-Archive .tools/node.zip .tools -Force
}
& .\.venv\Scripts\python.exe scripts/models.py
if($LASTEXITCODE){throw 'Model provisioning failed'}
& "$PSScriptRoot/build.ps1"
