@echo off
echo ============================================================
echo  Albion Fame ^& Silver Tracker - Installation
echo ============================================================
echo.

REM Verifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python non trouve. Installez Python depuis https://python.org
    pause
    exit /b 1
)
echo [OK] Python detecte

echo.
echo Aucune dependance supplementaire requise.
echo Le tracker utilise uniquement les modules standard de Python.
echo.
echo ============================================================
echo  Installation terminee.
echo  Lancez le tracker avec lancer.bat
echo  (clic droit ^> Executer en tant qu'administrateur)
echo ============================================================
echo.
pause
