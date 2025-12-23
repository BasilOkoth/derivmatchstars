@echo off
TITLE DigitMatch Pro - Push to GitHub
CD /D "%~dp0"

echo [1/3] Staging changes...
git add .

echo [2/3] Committing changes...
:: This uses the current date/time in the message
git commit -m "Update obfuscated bot files - %date% %time%"

echo [3/3] Pushing to GitHub...
git push origin main

echo.
echo ==================================================
echo   DONE! Your files are now on GitHub.
echo ==================================================
pause