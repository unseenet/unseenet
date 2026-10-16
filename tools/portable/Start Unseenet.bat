@echo off
rem Start Unseenet from this folder (Windows). Double-click it.
rem Windows may warn that the program is from an unknown publisher:
rem click "More info", then "Run anyway". See README.txt.
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%windows-x86_64\unseenet.exe"
if not exist "%EXE%" (
    echo Unseenet for Windows is not in this folder.
    pause
    exit /b 1
)
rem Windows Terminal shows the client best; the old console works too.
where wt >nul 2>nul
if %errorlevel%==0 (
    start "" wt --title Unseenet "%EXE%" %*
    exit /b 0
)
title Unseenet
"%EXE%" %*
if errorlevel 1 pause
