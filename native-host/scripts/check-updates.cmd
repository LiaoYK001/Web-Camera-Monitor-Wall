@echo off
setlocal
chcp 65001 >nul
set "RUNTIME=%~dp0"
set "DATA=%LOCALAPPDATA%\WebOBS\Native"
set "UPDATES=%DATA%\updates"
set "FEED="
if exist "%RUNTIME%update-feed.url" set /p FEED=<"%RUNTIME%update-feed.url"
if "%FEED%"=="" (
  echo No update feed is configured for this build.
  echo 此构建未配置更新源。
  pause
  exit /b 1
)
for /f "delims=" %%V in ('"%RUNTIME%python\python.exe" -c "import json;print(json.load(open(r'%RUNTIME%webobs-native-prototype.json'))['version'])"') do set "CURRENT=%%V"
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\native_updater.py" check --feed "%FEED%" --current "%CURRENT%" --output "%DATA%\run\update-check.json"
if errorlevel 1 (
  echo Update check failed; the current version was kept.
  pause
  exit /b 1
)
"%RUNTIME%python\python.exe" -c "import json;v=json.load(open(r'%DATA%\run\update-check.json'));print('Available:',v['version']) if v['status']=='available' else print('Current version is up to date.')"
echo.
choice /C YN /M "Download and install this update now? / 现在下载并安装更新"
if errorlevel 2 exit /b 0
echo Close WebOBS Wall completely before continuing.
echo 继续前请完全退出 WebOBS Wall。
pause
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\native_updater.py" install --manifest "%DATA%\run\update-check.json" --output "%UPDATES%" --data-root "%DATA%" --install-dir "%LOCALAPPDATA%\Programs\WebOBS Wall" --confirm
if errorlevel 1 (
  echo Update installation failed; the current version was kept.
  pause
  exit /b 1
)
echo Update installer launched. WebOBS Wall will reopen when installation completes.
pause
