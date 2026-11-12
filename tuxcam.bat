@echo off
REM Dev launcher for Windows — uses the MSYS2 UCRT64 Python.
REM Adjust MSYS2 root below if yours is not C:\msys64.
set MSYS2=C:\msys64
"%MSYS2%\ucrt64\bin\python.exe" "%~dp0tuxcam.py" %*
