@echo off
setlocal
cd /d "%~dp0.."
set "PATH=%CD%\runtimes\node;%CD%\cache\cargo\bin;%PATH%"
set "npm_config_cache=%CD%\cache\npm"
set "CARGO_HOME=%CD%\cache\cargo"
set "RUSTUP_HOME=%CD%\runtimes\rust"
set "CARGO_TARGET_DIR=%CD%\cache\tauri-target"
set "PLAYWRIGHT_BROWSERS_PATH=%CD%\runtimes\playwright"
set "PYTHONUTF8=1"
if not defined COMSPEC set "COMSPEC=%SystemRoot%\System32\cmd.exe"
set "TEMP=%CD%\tmp"
set "TMP=%CD%\tmp"
if not exist "%TMP%" mkdir "%TMP%"
"%CD%\runtimes\node\node.exe" "%CD%\runtimes\node\node_modules\npm\bin\npm-cli.js" %*
exit /b %ERRORLEVEL%
