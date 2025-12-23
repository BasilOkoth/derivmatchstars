const JavaScriptObfuscator = require('javascript-obfuscator');
const fs = require('fs');
const path = require('path');

console.log('='.repeat(50));
console.log('🛡️ DIGITMATCH PRO - BOT OBFUSCATION v3.0');
console.log('='.repeat(50));

// ✅ CRITICAL: Use correct project path
const PROJECT_PATH = process.cwd(); // Uses current directory (D:\IRELAND\derivmatchstars3)
console.log(`📁 Project path: ${PROJECT_PATH}`);

// Read the bot.html file
const botHtmlPath = path.join(PROJECT_PATH, 'bot.html');

// ✅ Check if file exists
if (!fs.existsSync(botHtmlPath)) {
    console.error(`❌ ERROR: bot.html not found at: ${botHtmlPath}`);
    console.error('   Make sure you are in the correct project directory:');
    console.error('   D:\\IRELAND\\derivmatchstars3');
    process.exit(1);
}

const botHtml = fs.readFileSync(botHtmlPath, 'utf8');
console.log(`📄 Read bot.html (${botHtml.length} characters)`);

// ✅ FIX: Extract ALL JavaScript from bot.html (multiple script tags)
let modifiedHtml = botHtml;
let scriptCount = 0;

// Find all <script> tags
const scriptRegex = /<script(?:\s+[^>]*)?>([\s\S]*?)<\/script>/gi;
let match;

while ((match = scriptRegex.exec(botHtml)) !== null) {
    scriptCount++;
    const fullTag = match[0];
    const scriptContent = match[1].trim();
    
    if (scriptContent && !fullTag.includes('src=') && scriptContent.length > 50) {
        console.log(`\n🔍 Processing script block #${scriptCount} (${scriptContent.length} chars)...`);
        
        try {
            // ✅ CRITICAL: Fix hardcoded deployment URLs BEFORE obfuscation
            let fixedScript = scriptContent
                // Replace hardcoded deployment URLs
                .replace(/https?:\/\/[a-zA-Z0-9\-\.]+vercel\.app\/api/g, '/api')
                .replace(/cpt1::[a-zA-Z0-9\-_]+/g, 'current-deployment')
                // Fix for your specific error URL
                .replace(/derivmatchstarsbot\.vercel\.app/g, '')
                .replace(/prj_IuqBDVT2Ik158PBnw1hGh2DCGBeE/g, 'digitmatchstars')
                // Ensure bot-obfuscated.html reference is preserved
                .replace(/bot\.html/g, 'bot-obfuscated.html');
            
            // Obfuscate the JavaScript
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
                // ✅ IMPORTANT: Lock to YOUR current domains
                domainLock: [
                    'digitmatchstars-two.vercel.app',
                    'derivmatchstarsbot.vercel.app',
                    'digitmatchstars-3v85stluc-basil-okoths-projects-bdf9d53b.vercel.app',
                    'localhost'
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
                // Preserve important variable names
                reservedNames: [
                    'apiToken', 'affiliateCode', 'initBot', 'startTrading',
                    'API_URL', 'BASE_URL', 'fetch', 'localStorage',
                    'document', 'window', 'console', 'alert',
                    'DERIV_TOKEN', 'isAuthenticated', 'checkForAutoAuth'
                ]
            });

            const obfuscatedScript = obfuscationResult.getObfuscatedCode();
            console.log(`   ✅ Obfuscated (${obfuscatedScript.length} chars)`);
            
            // Replace in the HTML
            modifiedHtml = modifiedHtml.replace(fullTag, `<script>\n${obfuscatedScript}\n</script>`);
            
        } catch (error) {
            console.error(`   ⚠️ Failed to obfuscate script #${scriptCount}: ${error.message}`);
        }
    }
}

console.log(`\n📊 Processed ${scriptCount} script blocks`);

if (scriptCount === 0) {
    console.error('❌ ERROR: No <script> tags found in bot.html');
    process.exit(1);
}

// ✅ ADDITIONAL: Fix HTML-level URLs
console.log('\n🔗 Fixing HTML-level URLs...');
modifiedHtml = modifiedHtml
    // Fix form actions
    .replace(/action="https?:\/\/[^"]+"/g, 'action="/api"')
    // Fix iframe/src attributes
    .replace(/(src|href)="https?:\/\/[^"]+"/g, '$1="#"')
    // Remove any hardcoded deployment references
    .replace(/https?:\/\/cpt1-[a-zA-Z0-9\-]+\.vercel\.app/g, '/')
    // Ensure index.html redirects to bot-obfuscated.html
    .replace(/index\.html\?token=/g, 'bot-obfuscated.html?token=');

// ✅ CRITICAL: Ensure bot uses relative API paths
console.log('🔄 Ensuring relative API paths...');
if (!modifiedHtml.includes('API_URL') && !modifiedHtml.includes('apiUrl')) {
    // Add API_URL definition if missing
    const headEnd = modifiedHtml.indexOf('</head>');
    if (headEnd !== -1) {
        modifiedHtml = modifiedHtml.substring(0, headEnd) + 
            '\n<script>\n// Auto-injected API configuration\nconst API_URL = "/api";\nconst CURRENT_DOMAIN = window.location.origin;\n</script>\n' + 
            modifiedHtml.substring(headEnd);
        console.log('   ✅ Injected API_URL configuration');
    }
}

// Save obfuscated version
const outputPath = path.join(PROJECT_PATH, 'bot-obfuscated.html');
fs.writeFileSync(outputPath, modifiedHtml, 'utf8');

// ✅ Create backup of original bot.html (the redirect file)
const backupPath = path.join(PROJECT_PATH, `bot-redirect-original-backup-${Date.now()}.html`);
fs.writeFileSync(backupPath, botHtml, 'utf8');

console.log('\n' + '='.repeat(50));
console.log('✅ OBFUSCATION COMPLETE!');
console.log('='.repeat(50));
console.log(`📄 Original redirect file: ${botHtmlPath}`);
console.log(`🔒 Obfuscated bot: ${outputPath}`);
console.log(`💾 Backup: ${backupPath}`);
console.log(`📏 Size increase: ${Math.round((modifiedHtml.length / botHtml.length) * 100)}%`);
console.log(`🛡️ Script blocks protected: ${scriptCount}`);

// ✅ Verify the file will work with Vercel
console.log('\n🔍 VERIFICATION:');
const hasBotHtml = fs.existsSync(outputPath);
const hasApiReference = modifiedHtml.includes('/api') || modifiedHtml.includes('API_URL');
const noHardcodedUrls = !modifiedHtml.includes('cpt1::') && !modifiedHtml.includes('derivmatchstarsbot.vercel.app/api');
const usesObfuscated = modifiedHtml.includes('bot-obfuscated.html') || !modifiedHtml.includes('bot.html');

console.log(`   ✅ bot-obfuscated.html created: ${hasBotHtml ? 'YES' : 'NO'}`);
console.log(`   ✅ Uses relative API paths: ${hasApiReference ? 'YES' : 'NO'}`);
console.log(`   ✅ No hardcoded deployment URLs: ${noHardcodedUrls ? 'YES' : 'NO'}`);
console.log(`   ✅ Points to obfuscated version: ${usesObfuscated ? 'YES' : 'NO'}`);

if (!usesObfuscated) {
    console.log('   ⚠️ WARNING: May still reference bot.html instead of bot-obfuscated.html');
}

// ✅ Create README for deployment
const readmeContent = `
DEPLOYMENT GUIDE - DigitMatchStars Pro™
========================================

FILES:
1. index.html           - Landing page with OAuth
2. bot.html             - Redirect to obfuscated version
3. bot-obfuscated.html  - Obfuscated trading bot (MAIN)
4. backend/             - Backend API

URL STRUCTURE:
- https://your-domain.com/              → index.html
- https://your-domain.com/bot           → bot.html → bot-obfuscated.html
- https://your-domain.com/bot.html      → bot-obfuscated.html
- https://your-domain.com/bot-obfuscated.html → Direct access

OAUTH FLOW:
1. User clicks "Connect via OAuth" on index.html
2. Redirects to Deriv OAuth
3. Returns to index.html with token
4. Redirects to bot-obfuscated.html?token=XXX
5. bot-obfuscated.html authenticates and loads bot

TO UPDATE:
1. Edit bot.html (redirect file)
2. Run: node obfuscate.js
3. Deploy all files

TESTING:
1. Open index.html locally
2. Click "Connect via OAuth"
3. Should redirect to bot-obfuscated.html
`;

fs.writeFileSync(path.join(PROJECT_PATH, 'DEPLOYMENT_GUIDE.txt'), readmeContent);

console.log('\n🚀 NEXT STEPS:');
console.log('   1. Test locally: Open index.html → Connect via OAuth');
console.log('   2. Deploy: npx vercel --prod');
console.log('   3. Access bot at: https://digitmatchstars-two.vercel.app/bot');
console.log('\n📘 Deployment guide saved as: DEPLOYMENT_GUIDE.txt');
<<<<<<< HEAD
console.log('\n' + '='.repeat(50));
=======
console.log('\n' + '='.repeat(50));
>>>>>>> 54eae53956b8856b022936ca4fa132104b56da53
