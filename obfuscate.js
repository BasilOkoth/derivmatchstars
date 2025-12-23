const JavaScriptObfuscator = require('javascript-obfuscator');
const fs = require('fs');
const path = require('path');

console.log('='.repeat(50));
console.log('🛡️ DIGITMATCH PRO - BOT OBFUSCATION v3.0 FIXED');
console.log('='.repeat(50));

const PROJECT_PATH = process.cwd();
console.log(`📁 Project path: ${PROJECT_PATH}`);

const botHtmlPath = path.join(PROJECT_PATH, 'bot.html');
if (!fs.existsSync(botHtmlPath)) {
    console.error(`❌ ERROR: bot.html not found at: ${botHtmlPath}`);
    process.exit(1);
}

const botHtml = fs.readFileSync(botHtmlPath, 'utf8');
console.log(`📄 Read bot.html (${botHtml.length} characters)`);

// ✅ FIX 1: Remove ALL script tags with src="#" BEFORE processing
console.log('\n🔍 Removing broken script tags with src="#"...');
let cleanedHtml = botHtml
    .replace(/<script\s+src=["']#["'][^>]*><\/script>/gi, '')
    .replace(/<link\s+href=["']#["'][^>]*>/gi, '');

// ✅ FIX 2: Add proper external resources
console.log('📦 Adding proper external resources...');
cleanedHtml = cleanedHtml.replace('</title>', `</title>
    <!-- External Resources -->
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://kit.fontawesome.com/a076d05399.js" crossorigin="anonymous"></script>
    <style>`);

// ✅ FIX 3: Extract and obfuscate JavaScript
let modifiedHtml = cleanedHtml;
let scriptCount = 0;
const scriptRegex = /<script(?:\s+[^>]*)?>([\s\S]*?)<\/script>/gi;
let match;

while ((match = scriptRegex.exec(cleanedHtml)) !== null) {
    scriptCount++;
    const fullTag = match[0];
    const scriptContent = match[1].trim();
    
    // Skip external scripts (with src attribute) and empty scripts
    if (fullTag.includes('src=') || scriptContent.length < 10) {
        continue;
    }
    
    console.log(`\n🔍 Processing script block #${scriptCount} (${scriptContent.length} chars)...`);
    
    try {
        // Fix URLs before obfuscation
        let fixedScript = scriptContent
            .replace(/https?:\/\/[a-zA-Z0-9\-\.]+vercel\.app\/api/g, '/api')
            .replace(/bot\.html/g, 'bot-obfuscated.html');
        
        // Obfuscate JavaScript
        const obfuscationResult = JavaScriptObfuscator.obfuscate(fixedScript, {
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
            domainLock: [
                'digitmatchstars-two.vercel.app',
                'derivmatchstarsbot.vercel.app',
                'digitmatchstars-3v85stluc-basil-okoths-projects-bdf9d53b.vercel.app',
                'localhost',
                '127.0.0.1'
            ],
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
            unicodeEscapeSequence: false,
            // ✅ CRITICAL: Prevent obfuscator from breaking HTML strings
            reservedStrings: [
                'script', 'src', 'href', 'style', 'div', 'class',
                'id', 'type', 'text/javascript', 'text/css',
                '<', '>', '/', '"', "'", '=', ' ', '\n'
            ],
            reservedNames: [
                'apiToken', 'API_URL', 'CURRENT_DOMAIN', 'fetch',
                'document', 'window', 'localStorage', 'sessionStorage',
                'console', 'alert', 'setTimeout', 'setInterval',
                'DERIV_TOKEN', 'isAuthenticated', 'checkForAutoAuth',
                'WebSocket', 'JSON', 'XMLHttpRequest', 'FormData'
            ],
            // ✅ IMPORTANT: Don't obfuscate string literals that might be HTML
            stringArray: false  // Disable string array to prevent HTML corruption
        });

        const obfuscatedScript = obfuscationResult.getObfuscatedCode();
        
        // ✅ FIX 4: Sanitize obfuscated code to prevent syntax errors
        let sanitizedScript = obfuscatedScript
            // Ensure proper string escaping
            .replace(/\\'/g, "'")
            .replace(/\\"/g, '"')
            // Fix potential unclosed strings
            .replace(/([^\\])'(?=[^']*$)/g, "$1\\'")
            .replace(/([^\\])"(?=[^"]*$)/g, '$1\\"');
        
        console.log(`   ✅ Obfuscated (${sanitizedScript.length} chars)`);
        
        // Replace in HTML
        modifiedHtml = modifiedHtml.replace(fullTag, `<script>\n${sanitizedScript}\n</script>`);
        
    } catch (error) {
        console.error(`   ⚠️ Failed to obfuscate script #${scriptCount}: ${error.message}`);
        console.error(`   Keeping original script for this block`);
    }
}

console.log(`\n📊 Processed ${scriptCount} script blocks`);

// ✅ FIX 5: Ensure no broken script tags remain
modifiedHtml = modifiedHtml
    .replace(/<script\s+src\s*=\s*["']#["'][^>]*>/gi, '')
    .replace(/<link\s+href\s*=\s*["']#["'][^>]*>/gi, '');

// ✅ FIX 6: Add API configuration if missing
if (!modifiedHtml.includes('API_URL') && !modifiedHtml.includes('apiUrl')) {
    const headEnd = modifiedHtml.indexOf('</head>');
    if (headEnd !== -1) {
        modifiedHtml = modifiedHtml.substring(0, headEnd) + 
            '\n<script>\n// Auto-injected API configuration\nconst API_URL = "/api";\nconst CURRENT_DOMAIN = window.location.origin;\n</script>\n' + 
            modifiedHtml.substring(headEnd);
        console.log('   ✅ Injected API_URL configuration');
    }
}

// ✅ FIX 7: Save with proper encoding
const outputPath = path.join(PROJECT_PATH, 'bot-obfuscated.html');
fs.writeFileSync(outputPath, modifiedHtml, 'utf8');

// Create backup
const backupPath = path.join(PROJECT_PATH, `bot-original-backup-${Date.now()}.html`);
fs.writeFileSync(backupPath, botHtml, 'utf8');

console.log('\n' + '='.repeat(50));
console.log('✅ OBFUSCATION COMPLETE!');
console.log('='.repeat(50));
console.log(`📄 Output: ${outputPath}`);
console.log(`💾 Backup: ${backupPath}`);

// Verification
console.log('\n🔍 VERIFICATION:');
const verificationChecks = [
    { name: 'No src="#" script tags', test: !modifiedHtml.includes('src="#"') },
    { name: 'Has proper external resources', test: modifiedHtml.includes('fontawesome.com') },
    { name: 'Uses bot-obfuscated.html', test: modifiedHtml.includes('bot-obfuscated.html') },
    { name: 'Has API_URL definition', test: modifiedHtml.includes('API_URL') },
    { name: 'Valid HTML structure', test: modifiedHtml.startsWith('<!DOCTYPE html>') }
];

verificationChecks.forEach(check => {
    console.log(`   ${check.test ? '✅' : '❌'} ${check.name}`);
});

if (!verificationChecks[4].test) {
    console.error('\n⚠️ WARNING: HTML structure may be corrupted!');
}

console.log('\n🚀 NEXT STEPS:');
console.log('   1. Test: Open bot-obfuscated.html directly in browser');
console.log('   2. Check DevTools Console for errors');
console.log('   3. Deploy: npx vercel --prod');
console.log('\n' + '='.repeat(50));
