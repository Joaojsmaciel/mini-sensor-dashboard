@echo off
REM ==========================================================================
REM  MINI SENSOR DASHBOARD - gera a pasta "dependencias" para instalar em um
REM  PC SEM internet. Execute em um PC COM internet onde o projeto ja funciona.
REM
REM  Opcao:  preparar_pacote_offline.bat -SemArduinoIDE   (nao baixa a IDE)
REM ==========================================================================
setlocal
cd /d "%~dp0"
title MINI SENSOR DASHBOARD - Pacote offline
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preparar_pacote_offline.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
