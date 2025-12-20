const JavaScriptObfuscator = require('javascript-obfuscator');
const fs = require('fs');
const path = require('path');

console.log('🛡️ Starting bot obfuscation...');

// Read the bot.html file
const botHtmlPath = path.join(__dirname, 'bot.html');
const botHtml = fs.readFileSync(botHtmlPath, 'utf8');

// Extract JavaScript from bot.html
const scriptStart = botHtml.indexOf('<script>');
const scriptEnd = botHtml.lastIndexOf('</script>');
const scriptContent = botHtml.substring(scriptStart + 8, scriptEnd);

console.log(`📄 Original script size: ${scriptContent.length} characters`);

// Obfuscate the JavaScript
const obfuscationResult = JavaScriptObfuscator.obfuscate(scriptContent, {
    compact: true,
    controlFlowFlattening: true,
    controlFlowFlatteningThreshold: 0.75,
    numbersToExpressions: true,
    simplify: true,
    stringArray: true,
    stringArrayEncoding: ['base64'],
    stringArrayThreshold: 0.75,
    deadCodeInjection: true,
    deadCodeInjectionThreshold: 0.4,
    debugProtection: true,
    debugProtectionInterval: 4000,
    disableConsoleOutput: false,
    domainLock: [], // Add your domain here in production
    renameGlobals: false,
    rotateStringArray: true,
    selfDefending: true,
    sourceMap: false,
    sourceMapMode: 'separate',
    stringArrayWrappersCount: 1,
    stringArrayWrappersChainedCalls: true,
    stringArrayWrappersParametersMaxCount: 2,
    stringArrayWrappersType: 'variable',
    stringArrayIndexShift: true,
    target: 'browser',
    transformObjectKeys: true,
    unicodeEscapeSequence: false
});

const obfuscatedScript = obfuscatedResult.getObfuscatedCode();
console.log(`🔒 Obfuscated script size: ${obfuscatedScript.length} characters`);

// Create new HTML with obfuscated script
const newHtml = botHtml.substring(0, scriptStart + 8) + 
                obfuscatedScript + 
                botHtml.substring(scriptEnd);

// Save obfuscated version
const outputPath = path.join(__dirname, 'bot-obfuscated.html');
fs.writeFileSync(outputPath, newHtml);

console.log(`✅ Obfuscated bot saved to: ${outputPath}`);
console.log('🛡️ Obfuscation complete!');