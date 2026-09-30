@echo off
REM Build AnimePaheDL.exe on Windows 10/11 (needs Python 3.10+ from python.org or winget).
setlocal
cd /d "%~dp0"
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt -r requirements-dev.txt || goto :error
python -m pytest -q || goto :error
pyinstaller AnimePaheDL.spec --noconfirm || goto :error
echo.
echo Build finished: %~dp0dist\AnimePaheDL\AnimePaheDL.exe
exit /b 0
:error
echo Build failed.
exit /b 1
