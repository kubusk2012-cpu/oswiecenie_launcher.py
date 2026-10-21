@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Instaluje PyInstaller...
python -m pip install --upgrade pyinstaller || goto :blad

set IKONA=
if exist ikona.ico set IKONA=--icon ikona.ico

echo Buduje launcher...
python -m PyInstaller --noconfirm --onefile --windowed --name "Oswiecenie-Launcher" %IKONA% oswiecenie_launcher.py || goto :blad

echo.
echo Gotowe: dist\Oswiecenie-Launcher.exe
pause
exit /b 0

:blad
echo.
echo Budowanie nie powiodlo sie. Sprawdz, czy Python jest zainstalowany i dodany do PATH.
pause
exit /b 1
