@echo off
REM ==========================================================================
REM  MINI SENSOR DASHBOARD - instala todas as dependencias neste PC
REM  (Python 3.12, pacotes Python, Arduino IDE, core AVR e bibliotecas).
REM  Usa a pasta "dependencias" se existir (instalacao offline).
REM
REM  Opcoes:  instalar_dependencias.bat -SemArduino       so o dashboard
REM           instalar_dependencias.bat -SemVerificacao   pula testes/compilacao
REM ==========================================================================
setlocal
cd /d "%~dp0"
title MINI SENSOR DASHBOARD - Instalacao

REM Arquivos copiados de um .zip baixado da internet ficam "bloqueados" pelo
REM Windows; o desbloqueio vale apenas para os arquivos desta pasta.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0.' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_dependencias.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
