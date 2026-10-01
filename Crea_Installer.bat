@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Mosaico Camere - creazione del programma di installazione
echo ==========================================================
echo   Creazione di Setup_MosaicoCamere.exe   (UNA sola volta)
echo ==========================================================
echo.

if exist "%~dp0mosaico_cam.py" goto t1
echo ERRORE: mosaico_cam.py non e' in questa cartella.
goto fine
:t1
if exist "%~dp0MosaicoCamere.iss" goto t2
echo ERRORE: MosaicoCamere.iss non e' in questa cartella.
goto fine
:t2
if exist "%~dp0version_info.txt" goto t3
echo ERRORE: version_info.txt non e' in questa cartella.
goto fine
:t3
if exist "%~dp0CONDIZIONI_USO.txt" if exist "%~dp0LICENSE.txt" if exist "%~dp0THIRD_PARTY_NOTICES.txt" goto t4
echo ERRORE: mancano file di licenza. Servono: CONDIZIONI_USO.txt, LICENSE.txt, THIRD_PARTY_NOTICES.txt
goto fine
:t4
findstr /C:"[[CONTATTO]]" "%~dp0CONDIZIONI_USO.txt" >nul 2>&1
if errorlevel 1 goto t5
echo.
echo ATTENZIONE: in CONDIZIONI_USO.txt e' rimasto il segnaposto [[CONTATTO]].
echo Aprilo con il Blocco note, sostituiscilo con la tua email o il tuo sito
echo (punto 5, "Assistenza e funzioni premium"), salva e rilancia questo file.
goto fine
:t5

rem ---------- 1) PYTHON ----------
set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_ok
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto py_ok

echo [1/5] Python non trovato: provo a installarlo con winget...
where winget >nul 2>&1
if errorlevel 1 goto no_winget
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto py_ok
echo.
echo Python e' stato installato: CHIUDI questa finestra e riapri Crea_Installer.bat
goto fine

:no_winget
echo.
echo winget non e' disponibile su questo PC.
echo Installa Python da https://www.python.org/downloads/
echo Durante l'installazione spunta "Add python.exe to PATH", poi riapri questo file.
start "" https://www.python.org/downloads/
goto fine

:py_ok
echo [1/5] Python trovato:
%PY% --version
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto no_tk

rem ---------- 2) LIBRERIE + PYINSTALLER ----------
echo [2/5] Installo le librerie necessarie (puo' richiedere qualche minuto)...
%PY% -m pip install --disable-pip-version-check opencv-python pillow numpy onvif-zeep pyinstaller
if errorlevel 1 goto pip_err

set "WSDL="
%PY% "%~dp0mosaico_cam.py" --wsdl-path > "%TEMP%\wsdl.txt"
set /p WSDL=<"%TEMP%\wsdl.txt"
if defined WSDL if exist "%WSDL%\devicemgmt.wsdl" goto wsdl_ok
echo ERRORE: non trovo i file WSDL di onvif-zeep.
goto fine
:wsdl_ok

rem ---------- 3) CREA IL PROGRAMMA (.exe) ----------
echo [3/5] Creo il programma (2-5 minuti, e' normale che sembri fermo)...
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"
if exist "%~dp0build" rmdir /s /q "%~dp0build"
%PY% -m PyInstaller --noconfirm --clean --windowed --name MosaicoCamere ^
 --collect-submodules onvif --collect-submodules zeep ^
 --hidden-import lxml.etree --hidden-import lxml._elementpath ^
 --add-data "%WSDL%;wsdl" ^
 --version-file "%~dp0version_info.txt" mosaico_cam.py
if errorlevel 1 goto build_err
if exist "%~dp0dist\MosaicoCamere\MosaicoCamere.exe" goto build_ok
goto build_err
:build_ok

rem ---------- 4) VERIFICA ----------
echo [4/5] Verifica del programma creato...
del "%APPDATA%\MosaicoCamere\selftest.txt" >nul 2>&1
start /wait "" "%~dp0dist\MosaicoCamere\MosaicoCamere.exe" --selftest
if exist "%APPDATA%\MosaicoCamere\selftest.txt" type "%APPDATA%\MosaicoCamere\selftest.txt"
echo.

rem ---------- 5) PROGRAMMA DI INSTALLAZIONE (Inno Setup) ----------
call :find_iscc
if defined ISCC goto iscc_ok
echo [5/5] Inno Setup non trovato: lo installo con winget...
where winget >nul 2>&1
if errorlevel 1 goto no_inno
winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
call :find_iscc
if defined ISCC goto iscc_ok
goto no_inno

:iscc_ok
echo [5/5] Creo il programma di installazione...
"%ISCC%" "%~dp0MosaicoCamere.iss"
if errorlevel 1 goto iscc_err
echo.
echo ==========================================================
echo   FATTO!  Il programma di installazione (versione 1.0) e' qui:
echo   %~dp0installer_out\Setup_MosaicoCamere_1.0.exe
echo.
echo   Copia SOLO quel file sugli altri PC e fai doppio click.
echo ==========================================================
start "" "%~dp0installer_out"
goto fine_ok

:no_inno
echo.
echo Inno Setup non disponibile: creo al suo posto uno ZIP portatile.
powershell -NoProfile -Command "Compress-Archive -Path '%~dp0dist\MosaicoCamere' -DestinationPath '%~dp0MosaicoCamere_portatile.zip' -Force"
echo Creato: %~dp0MosaicoCamere_portatile.zip
echo (decomprimi sull'altro PC e avvia MosaicoCamere.exe)
goto fine_ok

:no_tk
echo.
echo ERRORE: questa versione di Python non include Tkinter.
echo Reinstalla Python da https://www.python.org/downloads/ lasciando spuntato "tcl/tk and IDLE".
goto fine

:pip_err
echo.
echo ERRORE: installazione delle librerie non riuscita. Controlla la connessione internet.
echo Se hai Python 3.13 o piu' recente prova con Python 3.12:  winget install -e --id Python.Python.3.12
goto fine

:build_err
echo.
echo ERRORE durante la creazione del programma. Copia il messaggio qui sopra e mandamelo.
goto fine

:iscc_err
echo.
echo ERRORE durante la creazione del programma di installazione. Copia il messaggio qui sopra e mandamelo.
goto fine

:fine_ok
echo.
pause
exit /b 0

:fine
echo.
pause
exit /b 1

:find_iscc
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
exit /b 0
