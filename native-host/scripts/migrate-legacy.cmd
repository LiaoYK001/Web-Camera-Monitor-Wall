@echo off
setlocal
chcp 65001 >nul
set "RUNTIME=%~dp0"
set "SOURCE=%LOCALAPPDATA%\WebOBS\config"
set "DEST=%LOCALAPPDATA%\WebOBS\Native\config"
echo WebOBS old-data import / 旧版 WebOBS 数据导入
echo.
echo Close the old WebOBS desktop app before continuing. The old files are read-only.
echo 继续前请完全退出旧版 WebOBS；本工具只读取旧文件。
echo.
echo Source / 来源: %SOURCE%
echo Destination / 目标: %DEST%
echo.
choice /C YN /M "Continue? / 是否继续"
if errorlevel 2 exit /b 1
"%RUNTIME%python\python.exe" -B "%RUNTIME%services\product\migrate_legacy.py" --source "%SOURCE%" --destination "%DEST%" --confirm-stopped --include-backup-key
if errorlevel 1 (
  echo.
  echo Import failed. Read the message above; the old installation was not changed.
  echo 导入失败；旧安装未被修改。
  pause
  exit /b 1
)
echo.
echo Import complete. Start WebOBS Wall and sign in with the existing account.
echo 导入完成。请启动 WebOBS Wall，并使用原账号登录。
pause
