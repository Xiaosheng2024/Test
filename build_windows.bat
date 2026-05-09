@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    py -3 -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller --clean --noconfirm model_system.spec

if not exist dist\ModelSystem\ModelSystem.exe (
    echo Build failed: dist\ModelSystem\ModelSystem.exe not found.
    exit /b 1
)

echo.
echo EXE build complete:
echo %cd%\dist\ModelSystem\ModelSystem.exe
echo.
echo To create installer, install Inno Setup and run:
echo iscc installer\ModelSystem.iss

endlocal
