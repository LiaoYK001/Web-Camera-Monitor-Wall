@echo off
setlocal
chcp 65001 >nul
set "RUNTIME=%~dp0"
set "DATA=%LOCALAPPDATA%\WebOBS\Native"
set "UPDATES=%DATA%\updates"
for %%I in ("%RUNTIME%.") do set "INSTALL=%%~fI"
if exist "%RUNTIME%.webobs-maintenance-origin" (
  set /p INSTALL=<"%RUNTIME%.webobs-maintenance-origin"
  goto run_check
)
set "INFO=%DATA%\run\maintenance-%RANDOM%-%RANDOM%.path"
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\native_updater.py" prepare-maintenance --runtime "%INSTALL%" --data-root "%DATA%" --output "%INFO%"
if errorlevel 1 (
  echo Could not prepare the independent update tool. / 无法准备独立更新工具。
  pause
  exit /b 1
)
set /p MAINT=<"%INFO%"
del "%INFO%" >nul 2>nul
start "WebOBS update" "%ComSpec%" /C ""%MAINT%\CHECK-UPDATES.cmd""
exit /b 0
:run_check
set "FEED="
if exist "%INSTALL%\update-feed.url" set /p FEED=<"%INSTALL%\update-feed.url"
if "%FEED%"=="" (
  echo No update feed is configured for this build.
  echo 此构建未配置更新源。
  pause
  exit /b 1
)
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\native_updater.py" check --feed "%FEED%" --current-runtime "%INSTALL%\webobs-native-prototype.json" --output "%DATA%\run\update-check.json" --exit-code
if errorlevel 2 (
  echo Current version is up to date. / 当前已是最新版本。
  pause
  exit /b 0
)
if errorlevel 1 (
  echo Update check failed; the current version was kept.
  pause
  exit /b 1
)
echo.
choice /C YN /M "Download and install this update now? / 现在下载并安装更新"
if errorlevel 2 (
  "%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\native_updater.py" finish-maintenance
  exit /b 0
)
echo Close WebOBS Wall completely before continuing.
echo 继续前请完全退出 WebOBS Wall。
pause
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\native_updater.py" install --manifest "%DATA%\run\update-check.json" --output "%UPDATES%" --data-root "%DATA%" --install-dir "%INSTALL%" --current-runtime "%INSTALL%\webobs-native-prototype.json" --confirm
if errorlevel 1 (
  echo Update installation failed; the current version was kept.
  pause
  exit /b 1
)
echo Update installed. Start WebOBS Wall from its shortcut.
echo 更新已安装。请从快捷方式启动 WebOBS Wall。
pause
