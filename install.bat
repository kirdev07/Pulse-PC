@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Установка Pulse PC
echo ================================================
echo   Pulse PC: установка (только Python, без exe)
echo ================================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
    echo Python не найден.
    echo Скачайте его на https://www.python.org/downloads/ и при установке
    echo поставьте галочку "Add python.exe to PATH". Потом запустите install.bat снова.
    echo.
    pause
    exit /b 1
)

%PY% launcher.py --install
if errorlevel 1 (
    echo.
    echo Установка не завершилась. Сообщение об ошибке выше.
    pause
    exit /b 1
)
echo.
echo Автозапуск вместе с Windows можно включить в программе: Настройки - "Запускать Pulse PC вместе с Windows".
echo.
choice /c YN /m "Запустить Pulse PC сейчас"
if errorlevel 2 exit /b 0
%PY% launcher.py
