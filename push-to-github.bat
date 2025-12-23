@echo off
TITLE DigitMatch Pro - Quick Update
CD /D "%~dp0"

echo [1/2] Obfuscating Bot...
node obfuscate.js

echo [2/2] Pushing to GitHub...
git add .
git commit -m "Bot Update: %date% %time%"
git push origin main

echo.
echo SUCCESS! Your GitHub is updated.
pause