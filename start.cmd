@echo off
start "" "%SystemRoot%\System32\wscript.exe" //nologo "%~dp0start.vbs" %*
exit /b
