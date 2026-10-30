@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === KinDesk: building KinDesk.exe ===
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if not defined PY (
  python --version >nul 2>nul && set PY=python
)
if not defined PY goto nopython
echo Python: 
%PY% --version
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name KinDesk --icon KinDesk.ico kindesk.py
if errorlevel 1 goto fail
copy /y dist\KinDesk.exe KinDesk.exe >nul
echo.
echo DONE: KinDesk.exe is in this folder. You can delete build, dist and *.spec.
pause
exit /b 0
:nopython
echo.
echo Python is not installed (or only the empty Microsoft Store stub is present).
echo 1. Download 64-bit Python 3.12+ from https://www.python.org/downloads/windows/
echo 2. In the installer CHECK "Add python.exe to PATH" and "tcl/tk".
echo 3. Run build.bat again.
echo.
echo Or just run the program without building:  py -3 kindesk.py   (after installing Python).
start https://www.python.org/downloads/windows/
pause
exit /b 1
:fail
echo.
echo BUILD FAILED. Send the text above to Claude.
pause
exit /b 1
