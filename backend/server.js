require('dotenv').config();
const express = require('express');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

// CORS configuration for production
const allowedOrigins = process.env.NODE_ENV === 'production' 
    ? [
        'https://digitmatch-pro.vercel.app',
        'https://digitmatchpro.vercel.app',
        'https://*.vercel.app'
      ]
    : [
        'http://localhost:3000',
        'http://localhost:8000',
        'http://localhost:8080',
        'file://'
      ];

app.use(cors({
    origin: function(origin, callback) {
        // Allow requests with no origin (like mobile apps or curl requests)
        if (!origin) return callback(null, true);
        
        if (allowedOrigins.some(allowed => origin.includes(allowed))) {
            callback(null, true);
        } else {
            console.log('🚫 CORS blocked origin:', origin);
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
        next();
    });
}

// GET affiliate code (protected in production)
app.get('/api/get-affiliate-code', (req, res) => {
    // In production, you could add authentication here
    const affiliateCode = process.env.AFFILIATE_CODE || '0rfpRaHuZeFMjdsyM5hasGNd7ZgqdRLk';
    
    res.json({
        success: true,
        code: affiliateCode,
        message: 'Affiliate code retrieved successfully'
    });
});

// Verify API token
app.post('/api/verify-token', (req, res) => {
    const { apiToken, affiliateCode } = req.body;
    
    console.log('🔐 Token verification request received');
    
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
                    affiliateCode: affiliateCode
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

// Get bot configuration
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
        version: '2.0.0'
    };
    
    res.json({
        success: true,
        config: config,
        botUrl: 'bot.html',
        message: 'Bot configuration loaded successfully'
    });
});

// Track referral
app.post('/api/track-referral', (req, res) => {
    const { email, affiliateCode, ip, userAgent } = req.body;
    
    console.log('📊 Referral tracked:', { email, affiliateCode });
    
    // In production, save to database
    res.json({
        success: true,
        message: 'Referral tracked successfully'
    });
});

// Health check endpoint
app.get('/api/health', (req, res) => {
    res.json({ 
        status: 'OK', 
        environment: process.env.NODE_ENV || 'development',
        timestamp: new Date().toISOString(),
        version: '1.0.0'
    });
});

// Error handling middleware
app.use((err, req, res, next) => {
    console.error('❌ Server error:', err.stack);
    res.status(500).json({
        success: false,
        message: 'Internal server error',
        error: process.env.NODE_ENV === 'development' ? err.message : undefined
    });
});

// 404 handler
app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: 'Endpoint not found'
    });
});

// Start server
app.listen(PORT, () => {
    console.log(`🚀 Server running on port ${PORT}`);
    console.log(`🌐 Environment: ${process.env.NODE_ENV || 'development'}`);
    console.log(`🔗 Health check: http://localhost:${PORT}/api/health`);
    console.log(`📊 Affiliate code endpoint: http://localhost:${PORT}/api/get-affiliate-code`);
});