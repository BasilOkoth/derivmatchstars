@echo off
chcp 65001 >nul
echo ========================================================
echo   DIGITMATCH PRO - BOT OBFUSCATION & DEPLOYMENT v1.0
echo ========================================================
echo.

REM Check if Node.js is installed
where node >nul 2>nul
if errorlevel 1 (
    echo ❌ ERROR: Node.js is not installed or not in PATH!
    echo.
    echo Please install Node.js from: https://nodejs.org/
    echo Then run this script again.
    echo.
    pause
    exit /b 1
)

REM Check if npm is installed
where npm >nul 2>nul
if errorlevel 1 (
    echo ❌ ERROR: npm is not installed!
    pause
    exit /b 1
)

REM Install required packages if not present
echo 📦 Checking/Installing required packages...
if not exist "node_modules" (
    echo Installing javascript-obfuscator...
    npm install javascript-obfuscator --save-dev
) else (
    if not exist "node_modules\javascript-obfuscator" (
        npm install javascript-obfuscator --save-dev
    )
)

REM Check if source files exist
echo.
echo 🔍 Checking source files...
if not exist "bot.html" (
    echo ❌ ERROR: bot.html not found!
    echo.
    echo Place this .bat file in the same folder as:
    echo   - bot.html (your bot HTML file)
    echo   - obfuscate.js (obfuscation script)
    echo.
    pause
    exit /b 1
)

if not exist "obfuscate.js" (
    echo ❌ ERROR: obfuscate.js not found!
    echo.
    echo Creating a new obfuscation script...
    echo.
    
    REM Create obfuscate.js if missing
    echo // Obfuscation script for DigitMatchStars Pro
    echo const JavaScriptObfuscator = require('javascript-obfuscator');
    echo const fs = require('fs');
    echo const path = require('path');
    echo.
    echo console.log('Starting obfuscation...');
    echo.
    echo // Your obfuscation code here
    echo // ... 
    ) > obfuscate.js
    
    echo ✅ Created obfuscate.js - Please add your obfuscation code!
    echo.
)

REM Create backup before obfuscation
echo 📁 Creating backup of current files...
if exist "bot-obfuscated.html" (
    copy "bot-obfuscated.html" "bot-obfuscated-backup-%date:~-4,4%%date:~-10,2%%date:~-7,2%-%time:~0,2%%time:~3,2%%time:~6,2%.html" >nul
)

REM Run obfuscation
echo.
echo 🔒 Starting obfuscation process...
echo ========================================================
node obfuscate.js
echo ========================================================

REM Check if obfuscation succeeded
if not exist "bot-obfuscated.html" (
    echo.
    echo ❌ ERROR: bot-obfuscated.html was not created!
    echo Obfuscation may have failed.
    echo.
    pause
    exit /b 1
)

REM Check file size
for %%F in ("bot-obfuscated.html") do set OBF_SIZE=%%~zF
for %%F in ("bot.html") do set ORIG_SIZE=%%~zF
set /a SIZE_PERCENT=(OBF_SIZE*100)/ORIG_SIZE

echo.
echo 📊 Obfuscation Results:
echo   Original: %ORIG_SIZE% bytes
echo   Obfuscated: %OBF_SIZE% bytes
echo   Size: %SIZE_PERCENT%%% of original

REM Verify the obfuscated file
echo.
echo 🔍 Verifying obfuscated file...
findstr /I "src=\"#\"" bot-obfuscated.html >nul
if not errorlevel 1 (
    echo ⚠️ WARNING: File contains broken src="#" attributes!
)

findstr /I "bot-obfuscated.html" bot-obfuscated.html >nul
if errorlevel 1 (
    echo ⚠️ WARNING: File may not reference itself correctly!
)

findstr /I "API_URL" bot-obfuscated.html >nul
if errorlevel 1 (
    echo ⚠️ WARNING: API_URL not found in obfuscated file!
)

echo.
echo ✅ Obfuscation complete!

REM Optional: Create deployment package
echo.
set /p CREATE_DEPLOY="Create deployment package? (y/n): "
if /i "%CREATE_DEPLOY%"=="y" (
    echo 📦 Creating deployment package...
    if not exist "deploy" mkdir deploy
    copy "index.html" "deploy\" >nul 2>nul
    copy "bot-obfuscated.html" "deploy\" >nul 2>nul
    copy "bot.html" "deploy\" >nul 2>nul
    copy "vercel.json" "deploy\" >nul 2>nul 2>nul
    
    REM Create deployment README
    echo # Deployment Package - DigitMatchStars Pro > deploy\README.md
    echo Generated: %date% %time% >> deploy\README.md
    echo. >> deploy\README.md
    echo ## Files: >> deploy\README.md
    echo - index.html - Landing page >> deploy\README.md
    echo - bot.html - Redirect file >> deploy\README.md
    echo - bot-obfuscated.html - Main bot (obfuscated) >> deploy\README.md
    echo - vercel.json - Vercel configuration >> deploy\README.md
    echo. >> deploy\README.md
    echo ## To deploy: >> deploy\README.md
    echo 1. cd deploy >> deploy\README.md
    echo 2. vercel --prod >> deploy\README.md
    
    echo ✅ Deployment package created in \deploy folder
)

REM Optional: Deploy to Vercel
echo.
set /p DEPLOY_NOW="Deploy to Vercel now? (y/n): "
if /i "%DEPLOY_NOW%"=="y" (
    echo 🚀 Deploying to Vercel...
    vercel --prod
    if errorlevel 1 (
        echo ⚠️ Vercel deployment may have failed
        echo Check your vercel.json configuration
    )
)

echo.
echo ========================================================
echo 🎉 OBFUSCATION & DEPLOYMENT COMPLETE!
echo ========================================================
echo.
echo Next steps:
echo 1. Test bot-obfuscated.html locally
echo 2. Check Console for any JavaScript errors
echo 3. Deploy: npx vercel --prod
echo 4. Access: https://your-domain.vercel.app/bot
echo.
pause
