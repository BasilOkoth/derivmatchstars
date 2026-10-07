// /api/publish-cycle.js
// DigitMatchStar Telegram publisher V3.2
// Settlement-safe: Telegram reports the FULL cycle result, not only
// the profit of the final winning contract.

const WEBSITE = process.env.DIGITMATCHSTAR_URL || 'https://www.digitmatchstar.com';
const DMS_API = (process.env.DMS_API_URL || 'https://digitmatchstar-api.onrender.com').replace(/\/+$/, '');

function clean(v, n = 180) {
  return String(v ?? '').replace(/[<>&]/g, '').trim().slice(0, n);
}

function money(v) {
  const n = Number(v || 0);
  return `${n >= 0 ? '+' : '-'}$${Math.abs(n).toFixed(2)}`;
}

// Telegram does not support arbitrary text font colours.
// Use a strong green/red status emoji plus bold HTML text.
function netResultLine(v) {
  const n = Number(v || 0);

  if (n > 0) {
    return `🟢 <b>NET CYCLE PROFIT: ${money(n)}</b>`;
  }

  if (n < 0) {
    return `🔴 <b>NET CYCLE LOSS: ${money(n)}</b>`;
  }

  return `⚪ <b>NET CYCLE RESULT: ${money(n)}</b>`;
}

function market(s) {
  const m = {
    R_10: 'Volatility 10 Index',
    R_25: 'Volatility 25 Index',
    R_50: 'Volatility 50 Index',
    R_75: 'Volatility 75 Index',
    R_100: 'Volatility 100 Index',
    '1HZ10V': 'Volatility 10 (1s) Index',
    '1HZ15V': 'Volatility 15 (1s) Index',
    '1HZ25V': 'Volatility 25 (1s) Index',
    '1HZ30V': 'Volatility 30 (1s) Index',
    '1HZ50V': 'Volatility 50 (1s) Index',
    '1HZ75V': 'Volatility 75 (1s) Index',
    '1HZ90V': 'Volatility 90 (1s) Index',
    '1HZ100V': 'Volatility 100 (1s) Index'
  };
  return m[s] || clean(s, 60) || 'Digit Match';
}

function allowed(id) {
  const list = String(process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS || '')
    .split(',')
    .map(x => x.trim())
    .filter(Boolean);
  return list.length > 0 && list.includes(String(id));
}

async function verifyPlatformSession(token, accountId) {
  const r = await fetch(`${DMS_API}/sessions`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }
  });
  const d = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = d?.detail || d?.error || `HTTP ${r.status}`;
    const e = new Error(`DigitMatchStar session verification failed: ${detail}`);
    e.status = r.status === 401 ? 401 : 502;
    throw e;
  }
  if (!Array.isArray(d)) {
    const e = new Error('DigitMatchStar backend returned an invalid session response');
    e.status = 502;
    throw e;
  }
  const session = d.find(x => String(x?.account_id || '') === String(accountId));
  if (!session) {
    const e = new Error('Selected Deriv account was not verified for this DigitMatchStar user');
    e.status = 403;
    throw e;
  }
  return {
    accountMode: String(session?.account_mode || session?.account_type || '').toUpperCase() === 'REAL'
      ? 'REAL'
      : 'DEMO'
  };
}

async function verifyDerivToken(token, accountId) {
  const r = await fetch('https://api.derivws.com/trading/v1/options/accounts', {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }
  });
  const d = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = d?.error?.message || d?.message || d?.error || `HTTP ${r.status}`;
    const e = new Error(`Deriv account verification failed: ${detail}`);
    e.status = r.status === 401 ? 401 : 502;
    throw e;
  }

  const rows = Array.isArray(d?.data) ? d.data : (d?.data ? [d.data] : []);
  const account = rows.find(x => String(x?.account_id || '') === String(accountId));
  if (!account) {
    const e = new Error('Selected Deriv account was not verified by this token');
    e.status = 403;
    throw e;
  }

  const explicit = String(
    account?.account_mode ??
    account?.account_type ??
    account?.type ??
    ''
  ).toUpperCase();

  let accountMode = 'REAL';
  if (
    explicit.includes('DEMO') ||
    explicit.includes('VIRTUAL') ||
    account?.is_virtual === true ||
    account?.is_virtual === 1 ||
    String(accountId).toUpperCase().startsWith('VRTC')
  ) {
    accountMode = 'DEMO';
  }

  return { accountMode };
}

function normalise(c) {
  if (!c || typeof c !== 'object') throw new Error('Missing cycle');

  const trades = Array.isArray(c.trades) ? c.trades.slice(0, 200) : [];

  return {
    id: clean(c.id, 100),
    symbol: clean(c.symbol, 40),
    digit: Number(c.digit),
    status: String(c.status || '').toUpperCase() === 'WIN' ? 'WIN' : 'STOPPED',
    finalReason: clean(c.finalReason, 200),
    winningTradeNumber: Number(c.winningTradeNumber || 0) || null,
    totalInvestment: Number(c.totalInvestment || 0),
    totalPayout: Number(c.totalPayout || 0),
    netPnL: Number(c.netPnL || 0),
    cyclePnlAuthoritative: c.cyclePnlAuthoritative === true,
    settlementConfirmed: c.settlementConfirmed === true,
    settlementContractId: clean(c.settlementContractId, 120),
    maxStake: Number(c.maxStake || 0),
    trades
  };
}

function lastWinningTrade(c) {
  const rows = Array.isArray(c.trades) ? c.trades : [];
  for (let i = rows.length - 1; i >= 0; i--) {
    const t = rows[i] || {};
    if (String(t.result || '').toUpperCase() === 'WIN') return t;
  }
  return rows.length ? rows[rows.length - 1] : null;
}

/*
 * The browser already sends:
 *   c.netPnL = st.pnl
 *
 * st.pnl is the server cycle ledger:
 *   prior losing-contract profits + confirmed winning-contract profit.
 *
 * For DIGITMATCH a losing contract loses its full stake, therefore:
 *
 *   priorLossStake = winningProfit - cycleNetPnL
 *   totalStakeUsed = winningStake + priorLossStake
 *
 * This gives the complete cycle investment without mistaking the final
 * winning-contract profit for the full-cycle profit.
 */
function deriveWinCycleTotals(c) {
  const winningTrade = lastWinningTrade(c);

  const winningStake = Math.max(0, Number(winningTrade?.stake || 0));
  const winningProfit = Number(winningTrade?.profit);
  const cycleNetPnL = Number(c.netPnL);

  let winningPayout = Math.max(0, Number(winningTrade?.payout || c.totalPayout || 0));

  if (
    (!Number.isFinite(winningPayout) || winningPayout <= 0) &&
    Number.isFinite(winningProfit)
  ) {
    winningPayout = Math.max(0, winningStake + winningProfit);
  }

  let totalStakeUsed = Number(c.totalInvestment || 0);

  if (
    Number.isFinite(winningProfit) &&
    Number.isFinite(cycleNetPnL) &&
    winningStake > 0
  ) {
    const priorLossStake = Math.max(0, winningProfit - cycleNetPnL);
    totalStakeUsed = winningStake + priorLossStake;
  }

  return {
    winningTrade,
    winningStake: Number(winningStake.toFixed(2)),
    winningProfit: Number.isFinite(winningProfit) ? Number(winningProfit.toFixed(2)) : null,
    winningPayout: Number(Math.max(0, winningPayout).toFixed(2)),
    totalStakeUsed: Number(Math.max(0, totalStakeUsed).toFixed(2)),
    cycleNetPnL: Number.isFinite(cycleNetPnL) ? Number(cycleNetPnL.toFixed(2)) : 0
  };
}

function caption(c, type) {
  const win = c.status === 'WIN';
  const n = c.trades.length;
  const account = type === 'REAL' ? 'REAL ACCOUNT' : 'DEMO ACCOUNT';

  if (win) {
    const totals = deriveWinCycleTotals(c);

    const lines = [
      `⭐ <b>DIGITMATCHSTAR — ${account}</b>`, '',
      `📈 <b>${market(c.symbol)}</b>`,
      `🎯 Target digit: <b>${Number.isFinite(c.digit) ? c.digit : '-'}</b>`,
      `✅ <b>MATCHED AT TRADE ${c.winningTradeNumber || n}</b>`
    ];

    if (c.settlementConfirmed) {
      lines.push(`💵 Total stake used: <b>$${totals.totalStakeUsed.toFixed(2)}</b>`);
      lines.push(`💰 Winning payout: <b>$${totals.winningPayout.toFixed(2)}</b>`);
      lines.push(netResultLine(totals.cycleNetPnL));
      lines.push('🔒 Deriv settlement: <b>CONFIRMED</b>');
    }

    lines.push('');
    lines.push(
      type === 'REAL'
        ? 'Real-money result. Trading involves risk.'
        : 'Demo result using virtual funds.'
    );
    lines.push('Trading involves risk, and past results do not guarantee future performance.');
    lines.push('');
    lines.push('🚀 <b>Experience DigitMatchStar</b>');
    lines.push(WEBSITE);

    return lines.join('\n');
  }

  return [
    `⭐ <b>DIGITMATCHSTAR — ${account}</b>`, '',
    `📈 <b>${market(c.symbol)}</b>`,
    `🎯 Target digit: <b>${Number.isFinite(c.digit) ? c.digit : '-'}</b>`,
    `🛑 <b>CYCLE STOPPED AFTER ${n} TRADE${n === 1 ? '' : 'S'}</b>`,
    netResultLine(c.netPnL), '',
    'The selected digit did not match within the configured trade limit.', '',
    'Trading involves risk, and past results do not guarantee future performance.', '',
    '🚀 <b>Experience DigitMatchStar</b>',
    WEBSITE
  ].join('\n');
}

function envStatus() {
  return {
    TELEGRAM_BOT_TOKEN: Boolean(String(process.env.TELEGRAM_BOT_TOKEN || '').trim()),
    TELEGRAM_ADMIN_CHAT_ID: Boolean(String(process.env.TELEGRAM_ADMIN_CHAT_ID || '').trim()),
    TELEGRAM_CHAT_ID: Boolean(String(process.env.TELEGRAM_CHAT_ID || '').trim()),
    TELEGRAM_PUBLISH_ACCOUNT_IDS: Boolean(String(process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS || '').trim()),
    TELEGRAM_APPROVER_USER_IDS: Boolean(String(process.env.TELEGRAM_APPROVER_USER_IDS || '').trim()),
    TELEGRAM_WEBHOOK_SECRET: Boolean(String(process.env.TELEGRAM_WEBHOOK_SECRET || '').trim()),
    DMS_API_URL: Boolean(String(process.env.DMS_API_URL || '').trim()),
    approvalRequired: String(process.env.TELEGRAM_REQUIRE_APPROVAL || 'true').toLowerCase() !== 'false',
    dualAuth: true
  };
}

function approvalRequired() {
  return String(process.env.TELEGRAM_REQUIRE_APPROVAL || 'true').toLowerCase() !== 'false';
}

async function telegramSend(payload) {
  const token = String(process.env.TELEGRAM_BOT_TOKEN || '').trim();
  if (!token) {
    const e = new Error('TELEGRAM_BOT_TOKEN is missing in this deployment');
    e.status = 500;
    throw e;
  }

  const r = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const d = await r.json().catch(() => ({}));

  if (!r.ok || !d?.ok) {
    const e = new Error(`Telegram sendMessage failed: ${d?.description || `HTTP ${r.status}`}`);
    e.status = 502;
    throw e;
  }

  return d.result;
}

async function sendApprovalPreview(text) {
  const adminChat = String(process.env.TELEGRAM_ADMIN_CHAT_ID || '').trim();
  if (!adminChat) {
    const e = new Error('TELEGRAM_ADMIN_CHAT_ID is missing in this deployment');
    e.status = 500;
    throw e;
  }

  await telegramSend({
    chat_id: adminChat,
    text: '🧾 <b>DigitMatchStar approval preview</b>\nReview the result below before it is posted publicly.',
    parse_mode: 'HTML',
    disable_web_page_preview: true
  });

  return telegramSend({
    chat_id: adminChat,
    text,
    parse_mode: 'HTML',
    disable_web_page_preview: true,
    reply_markup: {
      inline_keyboard: [
        [
          { text: '✅ APPROVE & PUBLISH', callback_data: 'dms:approve' },
          { text: '❌ REJECT', callback_data: 'dms:reject' }
        ],
        [{ text: '🚀 Open DigitMatchStar', url: WEBSITE }]
      ]
    }
  });
}

async function sendPublicPost(text) {
  const publicChat = String(
    process.env.TELEGRAM_CHAT_ID ||
    process.env.MAIN_CHANNEL_CHAT_ID ||
    ''
  ).trim();

  if (!publicChat) {
    const e = new Error('TELEGRAM_CHAT_ID / MAIN_CHANNEL_CHAT_ID is missing in this deployment');
    e.status = 500;
    throw e;
  }

  return telegramSend({
    chat_id: publicChat,
    text,
    parse_mode: 'HTML',
    disable_web_page_preview: true,
    reply_markup: {
      inline_keyboard: [[{ text: '🚀 Open DigitMatchStar', url: WEBSITE }]]
    }
  });
}

module.exports = async function handler(req, res) {
  if (req.method === 'GET') {
    return res.status(200).json({
      ok: true,
      version: 'telegram-cycle-net-v3.2',
      environment: envStatus()
    });
  }

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  try {
    const auth = String(req.headers.authorization || '');
    const bearer = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';
    if (!bearer) {
      return res.status(401).json({ error: 'Missing publisher bearer token' });
    }

    const accountId = String(req.body?.account_id || '').trim();
    if (!accountId) return res.status(400).json({ error: 'Missing account_id' });

    const requestedMode = String(
      req.headers['x-dms-auth-mode'] ||
      req.body?.auth_mode ||
      'platform'
    ).toLowerCase();

    let verified;
    let authMode;

    if (requestedMode === 'deriv') {
      verified = await verifyDerivToken(bearer, accountId);
      authMode = 'deriv';
    } else {
      verified = await verifyPlatformSession(bearer, accountId);
      authMode = 'platform';
    }

    if (!allowed(accountId)) {
      return res.status(403).json({
        error: 'This account is not authorized to publish to the official channel'
      });
    }

    const c = normalise(req.body?.cycle);
    if (!c.id || !c.trades.length) {
      return res.status(400).json({ error: 'Invalid or empty cycle' });
    }

    // Never publish a WIN without the exact Deriv settlement.
    if (c.status === 'WIN' && c.settlementConfirmed !== true) {
      return res.status(202).json({
        ok: true,
        published: false,
        pendingSettlement: true,
        cycleId: c.id,
        message: 'WIN held until authoritative Deriv settlement is available'
      });
    }

    const text = caption(c, verified.accountMode);

    if (approvalRequired()) {
      const preview = await sendApprovalPreview(text);
      return res.status(200).json({
        ok: true,
        published: false,
        pendingApproval: true,
        format: 'text',
        accountType: verified.accountMode,
        authMode,
        cycleId: c.id,
        approvalMessageId: preview?.message_id || null
      });
    }

    const published = await sendPublicPost(text);
    return res.status(200).json({
      ok: true,
      published: true,
      pendingApproval: false,
      format: 'text',
      accountType: verified.accountMode,
      authMode,
      cycleId: c.id,
      publicMessageId: published?.message_id || null
    });

  } catch (e) {
    console.error('[publish-cycle]', e);
    return res.status(e.status || 500).json({
      error: e.message || 'Publisher error',
      environment: envStatus()
    });
  }
};
