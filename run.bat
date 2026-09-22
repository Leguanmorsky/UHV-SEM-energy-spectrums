@echo off
REM Convenience launcher for Windows. First run: creates venv + installs deps.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -m venv .venv || python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)
python -m spectrum_app
endlocal
