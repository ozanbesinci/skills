@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\kur.py --target all
) else (
  python scripts\kur.py --target all
)
if errorlevel 1 echo Kurulum basarisiz. Yukaridaki hata mesajini kontrol edin.
pause
