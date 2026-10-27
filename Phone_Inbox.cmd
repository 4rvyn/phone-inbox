@echo off
rem Double-click to receive photos and files from the iPhone. Close the window when done.
rem Python is started directly (not through the py launcher) so closing the window reaches it straight away.
for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.executable)"') do set "PYEXE=%%p"
if not defined PYEXE (
    echo   Python 3 was not found. Install it from python.org, which includes the py launcher, then run setup.ps1.
    pause
    exit /b 1
)
"%PYEXE%" "%~dp0server.py"
if errorlevel 1 pause
