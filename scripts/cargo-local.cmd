@echo off
setlocal
cd /d "%~dp0.."
set "PATH=%CD%\cache\cargo\bin;%CD%\runtimes\node;%PATH%"
set "CARGO_HOME=%CD%\cache\cargo"
set "RUSTUP_HOME=%CD%\runtimes\rust"
set "CARGO_TARGET_DIR=%CD%\cache\tauri-target"
set "TEMP=%CD%\tmp"
set "TMP=%CD%\tmp"
if not exist "%TMP%" mkdir "%TMP%"
"%CD%\cache\cargo\bin\cargo.exe" %*
exit /b %ERRORLEVEL%
