@echo off
rem Paladin - demarrage en double-clic (Windows).
rem Premiere fois : cree l'environnement Python (.venv) et installe les dependances.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Premiere installation : creation de l'environnement Python dans .venv ...
  where py >nul 2>nul
  if not errorlevel 1 (py -3 -m venv .venv) else (python -m venv .venv)
  if not exist "%PY%" (
    echo Python 3.12+ introuvable. Installer Python 3.14 depuis python.org, puis relancer.
    goto :error
  )
)
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.lock
if errorlevel 1 goto :error
"%PY%" -m pip install --disable-pip-version-check -q --no-deps -e .
if errorlevel 1 goto :error
"%PY%" -m paladin %*
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Paladin n'a pas pu demarrer : le message ci-dessus indique la cause.
echo Aide : docs\GUIDE.md, section Depannage.
pause
exit /b 1
