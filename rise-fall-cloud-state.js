// Cross-device Rise/Fall research state for Vercel serverless.
// Uses Upstash/Vercel KV REST credentials from environment variables.

const MAX_BYTES = 1_400_000;
const LEASE_MS = 90_000;

function redisConfig() {
  const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL || '';
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN || '';
  return { url: url.replace(/\/$/, ''), token };
}

async function redisCommand(command) {
  const { url, token } = redisConfig();
  if (!url || !token) {
    const e = new Error('Cloud research store is not configured. Add UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN (or KV_REST_API_URL / KV_REST_API_TOKEN).');
    e.status = 503;
    throw e;
  }
  const r = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(command),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) {
    const e = new Error(j.error || `Cloud store HTTP ${r.status}`);
    e.status = 502;
    throw e;
  }
  return j.result;
}

async function verifyAdmin(token, accountId) {
  const r = await fetch('https://api.derivws.com/trading/v1/options/accounts', {
    headers: { Authorization: `Bearer ${token}` },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error('Could not verify Deriv account'); e.status = 401; throw e;
  }
  const rows = Array.isArray(d?.data) ? d.data : (d?.data ? [d.data] : []);
  const account = rows.find(x => String(x?.account_id || '') === String(accountId));
  if (!account) { const e = new Error('Selected Deriv account was not verified'); e.status = 403; throw e; }

  const allowed = String(process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS || '')
    .split(',').map(x => x.trim()).filter(Boolean);
  if (!allowed.length || !allowed.includes(String(accountId))) {
    const e = new Error('Cloud research state is restricted to the owner account'); e.status = 403; throw e;
  }
}

function keyFor(accountId, symbol) {
  return `dms:risefall:v1:${String(accountId)}:${String(symbol || 'R_10')}`;
}

function safeNum(v, fallback = 0) {
  const n = Number(v); return Number.isFinite(n) ? n : fallback;
}

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ ok: false, error: 'method_not_allowed' });
  }

  try {
    const auth = String(req.headers.authorization || '');
    const token = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';
    const accountId = String(req.body?.account_id || '').trim();
    const symbol = String(req.body?.symbol || 'R_10').trim();
    const action = String(req.body?.action || 'load').toLowerCase();
    const deviceId = String(req.body?.device_id || '').trim();

    if (!token) return res.status(401).json({ ok: false, error: 'missing_bearer_token' });
    if (!accountId) return res.status(400).json({ ok: false, error: 'account_id_required' });
    await verifyAdmin(token, accountId);

    const key = keyFor(accountId, symbol);
    const raw = await redisCommand(['GET', key]);
    let current = null;
    if (raw) {
      try { current = JSON.parse(raw); } catch (_) { current = null; }
    }

    if (action === 'load') {
      return res.status(200).json({ ok: true, state: current });
    }

    if (action === 'claim') {
      if (!current) return res.status(404).json({ ok: false, error: 'no_cloud_state' });
      current.collectorDeviceId = deviceId || current.collectorDeviceId || null;
      current.collectorHeartbeatAt = Date.now();
      current.updatedAt = new Date().toISOString();
      current.revision = safeNum(current.revision) + 1;
      await redisCommand(['SET', key, JSON.stringify(current)]);
      return res.status(200).json({ ok: true, state: current });
    }

    if (action !== 'save') {
      return res.status(400).json({ ok: false, error: 'unsupported_action' });
    }

    const incoming = req.body?.state;
    if (!incoming || typeof incoming !== 'object') {
      return res.status(400).json({ ok: false, error: 'state_required' });
    }
    if (incoming.schema !== 'DIGITMATCHSTAR_RISEFALL_CLOUD_V1') {
      return res.status(400).json({ ok: false, error: 'invalid_schema' });
    }

    const forceTakeover = req.body?.force_takeover === true;
    if (current?.collectorDeviceId && current.collectorDeviceId !== deviceId) {
      const age = Date.now() - safeNum(current.collectorHeartbeatAt, 0);
      if (age >= 0 && age < LEASE_MS && !forceTakeover) {
        return res.status(409).json({
          ok: false,
          error: 'collector_busy',
          collectorDeviceId: current.collectorDeviceId,
          collectorHeartbeatAt: current.collectorHeartbeatAt,
          state: current,
        });
      }
    }

    const incomingTicks = safeNum(incoming?.progress?.totalForwardTicks);
    const remoteTicks = safeNum(current?.progress?.totalForwardTicks);
    const incomingEpoch = safeNum(incoming?.progress?.lastFeatureEpoch);
    const remoteEpoch = safeNum(current?.progress?.lastFeatureEpoch);
    const sameCohort = !current || current?.cohort?.cohortId === incoming?.cohort?.cohortId;

    if (current && sameCohort && (incomingTicks < remoteTicks || (incomingTicks === remoteTicks && incomingEpoch < remoteEpoch))) {
      return res.status(409).json({ ok: false, error: 'stale_state', state: current });
    }

    const record = {
      ...incoming,
      collectorDeviceId: deviceId || current?.collectorDeviceId || null,
      collectorHeartbeatAt: Date.now(),
      updatedAt: new Date().toISOString(),
      revision: safeNum(current?.revision) + 1,
    };
    const serialized = JSON.stringify(record);
    if (Buffer.byteLength(serialized, 'utf8') > MAX_BYTES) {
      return res.status(413).json({ ok: false, error: 'state_too_large' });
    }

    await redisCommand(['SET', key, serialized]);
    return res.status(200).json({ ok: true, state: record });
  } catch (e) {
    return res.status(e.status || 500).json({ ok: false, error: e.message || 'cloud_state_error' });
  }
};
