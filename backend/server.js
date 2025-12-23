require('dotenv').config();
const express = require('express');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

// CORS configuration - UPDATED with ALL your domains
const allowedOrigins = process.env.NODE_ENV === 'production' 
    ? [
        // ✅ ADDED: Your current working domains
        'https://digitmatchstars-two.vercel.app',
        'https://derivmatchstarsbot.vercel.app',
        'https://digitmatchstars-3v85stluc-basil-okoths-projects-bdf9d53b.vercel.app',
        
        // Original domains (keep if still needed)
        'https://digitmatch-pro.vercel.app',
        'https://digitmatchpro.vercel.app',
        
        // Wildcard for safety
        'https://*.vercel.app'
      ]
    : [
        'http://localhost:3000',
        'http://localhost:8000',
        'http://localhost:8080',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:8000',
        'http://127.0.0.1:8080',
        'file://'
      ];

app.use(cors({
    origin: function(origin, callback) {
        // Allow requests with no origin (like mobile apps or curl requests)
        if (!origin) return callback(null, true);
        
        // Check against allowed origins
        const isAllowed = allowedOrigins.some(allowed => {
            // Handle regex patterns
            if (allowed instanceof RegExp) {
                return allowed.test(origin);
            }
            // Handle string patterns with wildcards
            if (allowed.includes('*')) {
                const regex = new RegExp(allowed.replace('.', '\\.').replace('*', '.*'));
                return regex.test(origin);
            }
            // Exact match or substring match
            return origin.includes(allowed) || origin === allowed;
        });
        
        if (isAllowed) {
            callback(null, true);
        } else {
            console.log('🚫 CORS blocked origin:', origin);
            console.log('📋 Allowed origins:', allowedOrigins);
            callback(new Error('Not allowed by CORS'));
        }
    },
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With']
}));

app.use(express.json());

// Production middleware
if (process.env.NODE_ENV === 'production') {
    app.use((req, res, next) => {
        // Security headers
        res.setHeader('X-Content-Type-Options', 'nosniff');
        res.setHeader('X-Frame-Options', 'DENY');
        res.setHeader('X-XSS-Protection', '1; mode=block');
        res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
        res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
        next();
    });
}

// GET affiliate code (protected in production)
app.get('/api/get-affiliate-code', (req, res) => {
    // Get affiliate code from environment or use default
    const affiliateCode = process.env.AFFILIATE_CODE || '0rfpRaHuZeFMjdsyM5hasGNd7ZgqdRLk';
    
    // Log request for debugging
    console.log('📋 Affiliate code request from:', req.get('origin'));
    
    res.json({
        success: true,
        code: affiliateCode,
        environment: process.env.NODE_ENV || 'development',
        domain: req.get('host'),
        message: 'Affiliate code retrieved successfully'
    });
});

// Verify API token
app.post('/api/verify-token', (req, res) => {
    const { apiToken, affiliateCode } = req.body;
    
    console.log('🔐 Token verification request received');
    console.log('📱 Origin:', req.get('origin'));
    
    // Validate input
    if (!apiToken) {
        return res.status(400).json({
            success: false,
            message: 'API token is required'
        });
    }
    
    // Simulate processing delay
    setTimeout(() => {
        // In production, you should validate the token properly
        // For now, we accept any token that looks valid
        if (apiToken && apiToken.length > 10) {
            // Generate verification token
            const verificationToken = 'verif_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            
            res.json({
                success: true,
                message: 'Token validated successfully!',
                token: verificationToken,
                user: {
                    email: 'user@deriv.com',
                    name: 'Deriv Trader',
                    loginid: 'CR' + Math.floor(Math.random() * 10000000),
                    verified: true,
                    affiliateCode: affiliateCode || process.env.AFFILIATE_CODE
                },
                serverInfo: {
                    environment: process.env.NODE_ENV || 'development',
                    timestamp: new Date().toISOString()
                }
            });
        } else {
            res.status(401).json({
                success: false,
                message: 'Invalid API token. Please check your token and try again.'
            });
        }
    }, 1000);
});

// Get bot configuration - UPDATED botUrl
app.post('/api/get-bot-config', (req, res) => {
    const { verificationToken } = req.body;
    
    if (!verificationToken) {
        return res.status(400).json({
            success: false,
            message: 'Verification token is required'
        });
    }
    
    // Basic token validation
    if (!verificationToken.startsWith('verif_')) {
        return res.status(401).json({
            success: false,
            message: 'Invalid verification token'
        });
    }
    
    // ✅ IMPORTANT: Use relative URL instead of hardcoded domain
    // This will work on ANY of your domains
    const botUrl = '/bot.html'; // Relative path works on all domains
    
    // Production bot configuration
    const config = {
        martingaleMultiplier: 2.0,
        maxConsecutiveLosses: 7,
        baseStake: 1.0,
        currency: 'USD',
        symbols: ['R_100', 'R_50', 'R_25'],
        strategy: 'DIGITMATCH_INSTANT',
        payout: 792.9,
        riskLevel: 'MEDIUM',
        version: '2.0.0',
        serverDomain: req.get('host') // For debugging
    };
    
    res.json({
        success: true,
        config: config,
        botUrl: botUrl, // ✅ Now uses relative path
        message: 'Bot configuration loaded successfully',
        serverInfo: {
            origin: req.get('origin'),
            environment: process.env.NODE_ENV
        }
    });
});

// Generate bot link endpoint - NEW ENDPOINT to fix your issue
app.post('/api/generate-bot-link', (req, res) => {
    const { verificationToken, account1, token1, currency1, account2, token2, currency2 } = req.body;
    
    // Validate inputs
    if (!verificationToken || !verificationToken.startsWith('verif_')) {
        return res.status(401).json({
            success: false,
            message: 'Valid verification token required'
        });
    }
    
    // ✅ CRITICAL FIX: Get current domain from request
    const currentDomain = req.get('host');
    const currentProtocol = req.protocol || 'https';
    const currentOrigin = req.get('origin') || `${currentProtocol}://${currentDomain}`;
    
    // Construct bot URL with current domain
    const botParams = new URLSearchParams({
        acct1: account1 || 'CR' + Math.floor(Math.random() * 10000000),
        token1: token1 || '',
        cur1: currency1 || 'USD',
        acct2: account2 || '',
        token2: token2 || '',
        cur2: currency2 || 'USD',
        state: 'state_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9),
        verif: verificationToken
    });
    
    // Use relative path - will work on ANY domain
    const botLink = `/bot.html?${botParams.toString()}`;
    
    // Alternative: Full URL with current origin
    const fullBotLink = `${currentOrigin}/bot.html?${botParams.toString()}`;
    
    res.json({
        success: true,
        botLink: botLink, // Relative path (recommended)
        fullBotLink: fullBotLink, // Full URL for reference
        message: 'Bot link generated successfully',
        serverInfo: {
            currentDomain: currentDomain,
            currentOrigin: currentOrigin,
            environment: process.env.NODE_ENV
        }
    });
});

// Track referral
app.post('/api/track-referral', (req, res) => {
    const { email, affiliateCode, ip, userAgent } = req.body;
    
    console.log('📊 Referral tracked:', { email, affiliateCode, origin: req.get('origin') });
    
    // In production, save to database
    res.json({
        success: true,
        message: 'Referral tracked successfully',
        origin: req.get('origin')
    });
});

// Health check endpoint - with more details
app.get('/api/health', (req, res) => {
    res.json({ 
        status: 'OK', 
        environment: process.env.NODE_ENV || 'development',
        timestamp: new Date().toISOString(),
        version: '1.0.0',
        server: {
            port: PORT,
            host: req.get('host'),
            origin: req.get('origin')
        },
        cors: {
            allowedOrigins: allowedOrigins,
            currentOrigin: req.get('origin'),
            isAllowed: allowedOrigins.some(origin => {
                const reqOrigin = req.get('origin');
                if (!reqOrigin) return false;
                if (origin instanceof RegExp) return origin.test(reqOrigin);
                if (origin.includes('*')) {
                    const regex = new RegExp(origin.replace('.', '\\.').replace('*', '.*'));
                    return regex.test(reqOrigin);
                }
                return reqOrigin.includes(origin);
            })
        }
    });
});

// Test endpoint to check current domain
app.get('/api/test-domain', (req, res) => {
    res.json({
        currentDomain: req.get('host'),
        currentOrigin: req.get('origin'),
        protocol: req.protocol,
        headers: req.headers,
        environment: process.env.NODE_ENV
    });
});

// Error handling middleware
app.use((err, req, res, next) => {
    console.error('❌ Server error:', err.message);
    console.error('🌐 Request origin:', req.get('origin'));
    console.error('📁 Request path:', req.path);
    
    // If it's a CORS error, provide more helpful message
    if (err.message === 'Not allowed by CORS') {
        return res.status(403).json({
            success: false,
            message: 'CORS Error: Your domain is not allowed to access this API',
            yourDomain: req.get('origin'),
            allowedDomains: allowedOrigins,
            fix: 'Add your domain to allowedOrigins array in server.js'
        });
    }
    
    res.status(500).json({
        success: false,
        message: 'Internal server error',
        error: process.env.NODE_ENV === 'development' ? err.message : undefined
    });
});

// 404 handler
app.use((req, res) => {
    console.log('🔍 404 - Path not found:', req.path);
    console.log('🌐 Origin:', req.get('origin'));
    
    res.status(404).json({
        success: false,
        message: 'Endpoint not found',
        path: req.path,
        method: req.method,
        yourDomain: req.get('origin')
    });
});

// Start server
app.listen(PORT, () => {
    console.log('='.repeat(50));
    console.log(`🚀 Server running on port ${PORT}`);
    console.log(`🌐 Environment: ${process.env.NODE_ENV || 'development'}`);
    console.log(`🔗 Health check: http://localhost:${PORT}/api/health`);
    console.log(`📊 Affiliate code endpoint: http://localhost:${PORT}/api/get-affiliate-code`);
    console.log(`🔧 CORS allowed origins:`);
    allowedOrigins.forEach(origin => console.log(`   • ${origin}`));
    console.log('='.repeat(50));
});