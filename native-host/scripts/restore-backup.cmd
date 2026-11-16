@echo off
setlocal
chcp 65001 >nul
set "RUNTIME=%~dp0"
set "DATA=%LOCALAPPDATA%\WebOBS\Native"
echo WebOBS configuration restore / WebOBS 配置恢复
echo.
echo Close WebOBS Wall completely before restoring.
echo 恢复前请完全退出 WebOBS Wall。
echo.
set /p "ARCHIVE=Backup file (.wobk) / 备份文件: "
if not exist "%ARCHIVE%" (
  echo Backup file not found.
  pause
  exit /b 1
)
if not exist "%DATA%\run\backup.key" (
  echo The local backup key is missing. Restore requires the original key file.
  echo 本机备份密钥缺失；恢复需要原密钥文件。
  pause
  exit /b 1
)
choice /C YN /M "Replace current configuration from this backup? / 是否用该备份替换当前配置"
if errorlevel 2 exit /b 0
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\backup\encrypted_backup.py" restore "%ARCHIVE%" --config-root "%DATA%\config" --key-file "%DATA%\run\backup.key"
if errorlevel 1 (
  echo Restore failed. The current configuration was kept.
  echo 恢复失败；当前配置已保留。
  pause
  exit /b 1
)
echo Restore complete. Start WebOBS Wall again.
echo 恢复完成；请重新启动 WebOBS Wall。
pause
