@echo off
REM Lancer en tant qu'Administrateur (requis pour la capture reseau)
net session >nul 2>&1
if errorlevel 1 (
    echo Ce programme doit etre lance en tant qu'Administrateur.
    echo Clic droit sur ce fichier ^> "Executer en tant qu'administrateur"
    pause
    exit /b 1
)

cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo Une erreur s'est produite. Verifiez que Python est installe et relancez en administrateur.
    pause
)
