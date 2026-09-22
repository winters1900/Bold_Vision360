param([switch]$WebOnly)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$configPath=Join-Path $projectRoot 'config.local.json'
if(!(Test-Path $configPath)){Copy-Item config.example.json $configPath}
$cfg=Get-Content $configPath -Raw | ConvertFrom-Json
if(!$WebOnly){
  $vswhere='C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
  $vsPath=& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  if(!$vsPath){throw 'Install Visual Studio Desktop development with C++ (MSVC x64 and Windows SDK).'}
  $vsVersion=& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationVersion
  $generator=if($vsVersion.StartsWith('18.')){'Visual Studio 18 2026'}else{'Visual Studio 17 2022'}
  & .\.venv\Scripts\cmake.exe -S native -B build/native -G $generator -A x64 "-DCAMERA_SDK=$($cfg.camera_sdk)" "-DMEDIA_SDK=$($cfg.media_sdk)"
  if($LASTEXITCODE){throw 'CMake configure failed'}
  & .\.venv\Scripts\cmake.exe --build build/native --config Release
  if($LASTEXITCODE){throw 'Native build failed'}
}
$nodeDir=Join-Path $projectRoot '.tools\node-v22.16.0-win-x64'
$env:PATH="$nodeDir;"+$env:PATH
Push-Location web
try { & "$nodeDir\npm.cmd" ci; if($LASTEXITCODE){throw 'npm ci failed'}; & "$nodeDir\npm.cmd" run build; if($LASTEXITCODE){throw 'Web build failed'} } finally {Pop-Location}
