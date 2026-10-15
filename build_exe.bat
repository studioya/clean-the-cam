@echo off
REM ============================================================
REM  Build CleanTheCAM.exe  -  run this once on the Windows machine
REM  Requires Python 3.9+ with "Add to PATH" ticked at install.
REM ============================================================

cd /d "%~dp0"

echo Installing / updating build tools...
python -m pip install --upgrade pyinstaller pywin32
if errorlevel 1 goto :nopython

echo.
echo Running the tests...
python -m pip install --upgrade pytest >nul
python -m pytest -q
if errorlevel 1 goto :testsfailed

echo.
echo Building CleanTheCAM.exe ...
python -m PyInstaller --onefile --noconsole --name CleanTheCAM --clean ^
    --hidden-import win32com.client CleanTheCAM.py
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo  Done.  The executable is at:  dist\CleanTheCAM.exe
echo  Copy that one file anywhere - nothing else is needed.
echo ============================================================
pause
exit /b 0

:nopython
echo.
echo Could not run Python. Install it from python.org and make sure
echo "Add python.exe to PATH" is ticked during setup.
pause
exit /b 1

:testsfailed
echo.
echo The tests failed - the exe was NOT built. See the messages above.
pause
exit /b 1

:failed
echo.
echo Build failed. See the messages above.
pause
exit /b 1
