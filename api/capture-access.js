// /api/capture-access.js
// Server-side authorization for the Premium Capture UI.

async function verify(token, accountId){
  const r = await fetch(
    'https://api.derivws.com/trading/v1/options/accounts',
    { headers: { Authorization: `Bearer ${token}` } }
  );

  const d = await r.json().catch(() => ({}));

  if(!r.ok){
    throw Object.assign(
      new Error('Could not verify Deriv account'),
      { status: 401 }
    );
  }

  const rows = Array.isArray(d?.data)
    ? d.data
    : (d?.data ? [d.data] : []);

  const account = rows.find(
    x => String(x?.account_id || '') === String(accountId)
  );

  if(!account){
    throw Object.assign(
      new Error('Selected Deriv account was not verified'),
      { status: 403 }
    );
  }

  return account;
}

function allowed(id){
  const list = String(
    process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS || ''
  )
    .split(',')
    .map(x => x.trim())
    .filter(Boolean);

  return list.length > 0 && list.includes(String(id));
}

module.exports = async function handler(req, res){
  if(req.method !== 'POST'){
    res.setHeader('Allow', 'POST');
    return res.status(405).json({
      error: 'method_not_allowed'
    });
  }

  try{
    const auth = String(req.headers.authorization || '');
    const token = auth.startsWith('Bearer ')
      ? auth.slice(7).trim()
      : '';

    if(!token){
      return res.status(401).json({
        authorized: false,
        error: 'Missing Deriv bearer token'
      });
    }

    const accountId = String(
      req.body?.account_id || ''
    ).trim();

    if(!accountId){
      return res.status(400).json({
        authorized: false,
        error: 'account_id is required'
      });
    }

    await verify(token, accountId);

    if(!allowed(accountId)){
      return res.status(403).json({
        authorized: false,
        error: 'Premium capture is restricted to the owner account'
      });
    }

    return res.status(200).json({
      ok: true,
      authorized: true,
      accountId
    });

  }catch(e){
    return res.status(e.status || 500).json({
      authorized: false,
      error: e.message || 'capture_access_error'
    });
  }
};
