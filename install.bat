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

REM Installer scapy
echo.
echo Installation de scapy...
pip install scapy --quiet
if errorlevel 1 (
    echo [ERREUR] Impossible d'installer scapy.
    pause
    exit /b 1
)
echo [OK] scapy installe

echo.
echo ============================================================
echo  ETAPE MANUELLE REQUISE : Installez npcap
echo ============================================================
echo.
echo  npcap est le driver de capture reseau (open-source, gratuit).
echo  Telechargez-le ici : https://npcap.com/#download
echo  Lors de l'installation, cochez "WinPcap API-compatible mode"
echo.
echo  Sans npcap, la capture de paquets ne fonctionnera pas.
echo ============================================================
echo.
echo Installation terminee. Lancez le tracker avec :
echo   lancer.bat   (clic droit ^> Executer en tant qu'administrateur)
echo.
pause
