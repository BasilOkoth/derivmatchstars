@echo off
TITLE DigitMatch Pro - Bot Obfuscation Tool
SETLOCAL

:: Force the script to use the folder where the .bat is located
CD /D "%~dp0"

echo ==================================================
echo   DIGITMATCH PRO - AUTOMATED OBFUSCATION
echo ==================================================
echo Current Directory: %CD%
echo.

:: Check if Node.js is installed
where node >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js is not installed. Please install it from https://nodejs.org/
    pause
    exit /b
)

:: Ensure a package.json exists so npm doesn't wander to D:\ root
IF NOT EXIST "package.json" (
    echo [INFO] Creating local package configuration...
    call npm init -y >nul
)

:: Install the specific missing module LOCALLY
IF NOT EXIST "node_modules\javascript-obfuscator" (
    echo [INFO] Installing javascript-obfuscator locally...
    call npm install javascript-obfuscator --save-dev
)

:: Execute the obfuscation script
echo.
echo [RUNNING] node obfuscate.js...
node obfuscate.js

:: Check result
IF %ERRORLEVEL% EQU 0 (
    echo.
    echo [SUCCESS] Obfuscation complete!
) ELSE (
    echo.
    echo [FAILED] The script crashed. Check if 'obfuscate.js' is in:
    echo %CD%
)

echo.
pause