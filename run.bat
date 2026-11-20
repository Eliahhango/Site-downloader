@echo off
setlocal enabledelayedexpansion
title Site Downloader ^& React Converter

:: Enable ANSI colors if supported
reg query HKCU\Console /v VirtualTerminalLevel >nul 2>&1
if %errorlevel% neq 0 (
    reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1
)

echo.
echo ===================================================================
echo     Site Downloader and React Converter - Launcher
echo ===================================================================
echo.

set "PY_CMD="

:: 1. Check for local virtual environment
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv\Scripts\python.exe"
    goto :PYTHON_READY
)

:: 2. Check for Python launcher (py -3)
py -3 -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py -3"
    goto :PYTHON_READY
)

:: 3. Check for standard python command
python -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
    goto :PYTHON_READY
)

:: 4. Check standard AppData install locations
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PY_CMD=%%D\python.exe"
        goto :PYTHON_READY
    )
)

:: 5. Python is not installed: attempt automated installation
echo [!] Python is not installed on this computer.
echo [*] Attempting automated Python installation via Windows Package Manager (winget)...
echo.

where winget >nul 2>&1
if %errorlevel% equ 0 (
    winget install Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    if %errorlevel% equ 0 (
        echo.
        echo [OK] Python installed successfully!
        for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
            if exist "%%D\python.exe" (
                set "PY_CMD=%%D\python.exe"
                goto :PYTHON_READY
            )
        )
    )
)

:: Fallback: Download official installer
echo [*] Downloading Python official installer...
set "TEMP_INSTALLER=%TEMP%\python_installer_%RANDOM%.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe', '%TEMP_INSTALLER%')"
if exist "%TEMP_INSTALLER%" (
    echo [*] Installing Python silently with PATH enabled (this may take a minute)...
    "%TEMP_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    del "%TEMP_INSTALLER%" >nul 2>&1
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if exist "%%D\python.exe" (
            set "PY_CMD=%%D\python.exe"
            goto :PYTHON_READY
        )
    )
)

echo.
echo [!] Automatic Python installation failed.
echo [!] Please install Python 3.10+ from https://www.python.org/downloads/
echo     (Make sure to check 'Add Python to PATH' during installation)
echo.
pause
exit /b 1

:PYTHON_READY
:: 6. Run Site Downloader (auto-bootstraps dependencies and starts OpenCode UI)
%PY_CMD% "%~dp0site_downloader.py" %*
if %errorlevel% neq 0 (
    echo.
    echo Exited with code %errorlevel%.
)
