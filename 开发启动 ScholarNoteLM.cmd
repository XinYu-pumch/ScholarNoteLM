@echo off
setlocal
cd /d "%~dp0"
set "NODE=%~dp0runtimes\node\node.exe"
if not exist "%NODE%" (
  echo Missing Windows Node runtime: runtimes\node\node.exe
  pause
  exit /b 1
)
"%NODE%" scripts\desktop.mjs dev
if errorlevel 1 pause
