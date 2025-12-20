@echo off
echo 🔒 Creating obfuscated bot...
echo.

cd /d "D:\IRELAND\derivmatchstars2"

:: Install obfuscator if not installed
if not exist "backend\node_modules\javascript-obfuscator" (
  echo Installing javascript-obfuscator...
  cd backend
  npm install javascript-obfuscator
  cd ..
)

:: Run obfuscation
node -e "
const path = require('path');
const fs = require('fs');
const backendPath = path.join(__dirname, 'backend');
const obfuscatorPath = path.join(backendPath, 'node_modules', 'javascript-obfuscator');
const JavaScriptObfuscator = require(obfuscatorPath);

const html = fs.readFileSync('bot.html', 'utf8');
const start = html.indexOf('<script>') + 8;
const end = html.lastIndexOf('</script>');
const js = html.substring(start, end);

const obfuscated = JavaScriptObfuscator.obfuscate(js, {
    compact: true,
    controlFlowFlattening: true,
    stringArray: true,
    stringArrayEncoding: ['base64']
}).getObfuscatedCode();

const result = html.substring(0, start) + obfuscated + html.substring(end);
fs.writeFileSync('bot-obfuscated.html', result);

console.log('✅ bot-obfuscated.html created!');
"

echo.
echo 🛡️ Obfuscation complete!
echo 📁 File: bot-obfuscated.html
pause