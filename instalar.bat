@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Instalando el Transcriptor (solo una vez)
echo ============================================
echo.

REM Busca un Python x64 (AMD64) version 3.10 o mayor.
REM En Surface con ARM, Whisper necesita el Python de 64 bits normal (x64).
set "PY="
for %%C in ("py -3.13" "py -3.12" "py -3.11" "py -3.10" "py -3.14" "python") do (
    if not defined PY (
        %%~C -c "import sysconfig,sys; sys.exit(0 if sysconfig.get_platform()=='win-amd64' and sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PY=%%~C"
    )
)

if not defined PY (
    echo No encontre un Python compatible.
    echo Tu Surface tiene procesador ARM: instala Python 3.13
    echo "Windows installer (64-bit)" desde https://www.python.org/downloads/windows/
    echo NO elijas el que dice ARM64. Revisa el archivo LEEME.txt
    echo.
    echo Versiones de Python que encontre en tu computadora:
    py -0p
    pause
    exit /b 1
)

echo Usando: %PY%
%PY% --version
echo.
if exist venv rmdir /s /q venv
echo Creando entorno privado del programa...
%PY% -m venv venv
if errorlevel 1 (
    echo No pude crear el entorno. Revisa el archivo LEEME.txt
    pause
    exit /b 1
)

echo Instalando Whisper (puede tardar unos minutos)...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install faster-whisper
if errorlevel 1 (
    echo.
    echo Hubo un error instalando Whisper. Revisa el archivo LEEME.txt
    pause
    exit /b 1
)

if not exist grabaciones mkdir grabaciones
if not exist transcripciones mkdir transcripciones

echo.
echo ============================================
echo   Instalacion terminada.
echo   Ahora copia tus audios a "grabaciones"
echo   y haz doble clic en transcribir.bat
echo ============================================
pause
