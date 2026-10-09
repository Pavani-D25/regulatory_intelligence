@echo off
rem RegTrack India - double-click to set up and start everything (runs start.ps1).
rem   start.bat -Stop        stop it again
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
rem keep the window open if something went wrong, so the message can be read
if errorlevel 1 pause
