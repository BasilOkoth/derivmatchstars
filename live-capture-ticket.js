// /api/live-capture-ticket.js
// Short-lived signed upload ticket for ADMIN-ONLY live screen captures.

const crypto = require('crypto');

function clean(v,n=120){
  return String(v??'')
    .replace(/[^a-zA-Z0-9_.:-]/g,'')
    .slice(0,n);
}

async function verify(token, accountId){
  const r=await fetch(
    'https://api.derivws.com/trading/v1/options/accounts',
    {headers:{Authorization:`Bearer ${token}`}}
  );

  const d=await r.json().catch(()=>({}));

  if(!r.ok){
    throw Object.assign(
      new Error('Could not verify Deriv account'),
      {status:401}
    );
  }

  const rows=Array.isArray(d?.data)
    ? d.data
    : (d?.data?[d.data]:[]);

  const account=rows.find(
    x=>String(x?.account_id||'')===String(accountId)
  );

  if(!account){
    throw Object.assign(
      new Error('Selected Deriv account was not verified'),
      {status:403}
    );
  }

  return account;
}

function allowed(id){
  const list=String(
    process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS||''
  )
    .split(',')
    .map(x=>x.trim())
    .filter(Boolean);

  return list.length>0 && list.includes(String(id));
}

function sign(payload, secret){
  const body=Buffer
    .from(JSON.stringify(payload))
    .toString('base64url');

  const sig=crypto
    .createHmac('sha256',secret)
    .update(body)
    .digest('base64url');

  return `${body}.${sig}`;
}

module.exports=async function handler(req,res){
  if(req.method!=='POST'){
    res.setHeader('Allow','POST');
    return res.status(405).json({
      error:'method_not_allowed'
    });
  }

  try{
    const auth=String(req.headers.authorization||'');
    const token=auth.startsWith('Bearer ')
      ? auth.slice(7).trim()
      : '';

    if(!token){
      return res.status(401).json({
        error:'Missing Deriv bearer token'
      });
    }

    const accountId=String(
      req.body?.account_id||''
    ).trim();

    const cycleId=clean(
      req.body?.cycle_id,
      100
    );

    const theme=clean(
      req.body?.theme || 'ultra-premium',
      40
    );

    if(!accountId||!cycleId){
      return res.status(400).json({
        error:'account_id and cycle_id are required'
      });
    }

    const account=await verify(token,accountId);

    if(!allowed(accountId)){
      return res.status(403).json({
        error:'This account is not authorized for premium capture'
      });
    }

    const secret=String(
      process.env.MEDIA_WORKER_SECRET||''
    ).trim();

    const worker=String(
      process.env.MEDIA_WORKER_URL||''
    )
      .trim()
      .replace(/\/+$/,'');

    if(!secret||!worker){
      return res.status(500).json({
        error:'Premium media worker is not configured'
      });
    }

    const now=Math.floor(Date.now()/1000);

    const payload={
      kind:'capture',
      captureAdmin:true,
      accountId,
      cycleId,
      accountType:
        String(account?.account_type||'').toLowerCase()==='real'
          ? 'REAL'
          : 'DEMO',
      theme,
      iat:now,
      exp:now+300
    };

    return res.status(200).json({
      ok:true,
      uploadUrl:`${worker}/compose-live`,
      ticket:sign(payload,secret),
      expiresIn:300,
      accountType:payload.accountType,
      theme
    });

  }catch(e){
    return res.status(e.status||500).json({
      error:e.message||'ticket_error'
    });
  }
};
