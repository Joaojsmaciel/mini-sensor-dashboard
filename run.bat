@echo off
REM ==========================================================================
REM  MINI SENSOR DASHBOARD - inicializador para Windows
REM  1. Procura o Python 3.9+ instalado
REM  2. Cria o ambiente virtual .venv na primeira execucao
REM  3. Instala/atualiza as dependencias quando requirements.txt mudar
REM  4. Abre o dashboard
REM ==========================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title MINI SENSOR DASHBOARD

set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "MARKER=%VENV_DIR%\requirements.installed"

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import pip" >nul 2>&1
    if not errorlevel 1 goto deps
    echo [AVISO] O ambiente .venv esta corrompido ou o Python foi atualizado. Recriando...
    rmdir /s /q "%VENV_DIR%"
)

echo [1/3] Procurando Python 3...
REM numpy 2.5.5 exige Python 3.12 ou superior; o 3.12 e o preferido.
set "PY_CMD="
set "PY_CHECK=import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
py -3.12 -c "%PY_CHECK%" >nul 2>&1 && set "PY_CMD=py -3.12"
if not defined PY_CMD (
    py -3 -c "%PY_CHECK%" >nul 2>&1 && set "PY_CMD=py -3"
)
if not defined PY_CMD (
    python -c "%PY_CHECK%" >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo.
    echo [ERRO] Python 3.12 ou superior nao foi encontrado.
    echo        Execute instalar_dependencias.bat, que instala tudo automaticamente,
    echo        ou instale o Python 3.12 em https://www.python.org/downloads/
    echo        marcando a opcao "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo [2/3] Criando ambiente virtual em .venv ...
%PY_CMD% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERRO] Falha ao criar o ambiente virtual.
    pause
    exit /b 1
)

:deps
fc /b "requirements.txt" "%MARKER%" >nul 2>&1
if not errorlevel 1 goto run

echo [3/3] Instalando dependencias (PyQt6, PySerial, PyQtGraph)...
"%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip >nul
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar as dependencias. Verifique sua conexao com a internet
    echo        e execute run.bat novamente. Se o erro persistir, apague a pasta .venv
    echo        Se o projeto estiver no OneDrive, pause a sincronizacao durante a instalacao.
    pause
    exit /b 1
)
copy /y "requirements.txt" "%MARKER%" >nul

:run
echo.
echo Iniciando o MINI SENSOR DASHBOARD...
echo (mantenha esta janela aberta; mensagens de erro aparecem aqui)
"%VENV_PY%" "%~dp0app\main.py"
if errorlevel 1 (
    echo.
    echo O dashboard foi encerrado com erro. Veja as mensagens acima.
    pause
)
endlocal
