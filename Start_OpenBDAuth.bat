@echo off
chcp 65001 >nul
title OpenBDAuth - Blu-ray Authoring Studio
cd /d "%~dp0"

echo =======================================================
echo Starte OpenBDAuth...
echo =======================================================
echo.

python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo =======================================================
    echo Das Programm wurde mit einem Fehler beendet.
    echo Bitte stelle sicher, dass alle Abhängigkeiten installiert sind.
    echo =======================================================
    pause
)
