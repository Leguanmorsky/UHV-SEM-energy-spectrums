@echo off
REM Convenience launcher for Windows. First run: creates venv + installs deps.
REM Portable: works wherever this folder lives (uses %~dp0), so you can copy the
REM whole folder to another PC and just double-click this file.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -m venv .venv || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Could not create the virtual environment.
        echo Make sure Python 3.8+ is installed and on PATH ^(https://python.org^).
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Installing dependencies failed. See the messages above.
        pause
        exit /b 1
    )
) else (
    call ".venv\Scripts\activate.bat"
)

REM Launch without a console window if pythonw is available, else fall back.
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m spectrum_app
) else (
    python -m spectrum_app
)
endlocal
