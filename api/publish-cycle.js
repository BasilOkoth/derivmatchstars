// /api/publish-cycle.js
const WEBSITE = process.env.DIGITMATCHSTAR_URL || 'https://www.digitmatchstar.com';

function clean(v, n=180){ return String(v ?? '').replace(/[<>&]/g,'').trim().slice(0,n); }
function cash(v){ const n=Number(v||0); return `${n>=0?'+':'-'}$${Math.abs(n).toFixed(2)}`; }
function market(s){
  const m={R_10:'Volatility 10 Index',R_25:'Volatility 25 Index',R_50:'Volatility 50 Index',R_75:'Volatility 75 Index',R_100:'Volatility 100 Index',
  '1HZ10V':'Volatility 10 (1s) Index','1HZ15V':'Volatility 15 (1s) Index','1HZ25V':'Volatility 25 (1s) Index','1HZ30V':'Volatility 30 (1s) Index',
  '1HZ50V':'Volatility 50 (1s) Index','1HZ75V':'Volatility 75 (1s) Index','1HZ90V':'Volatility 90 (1s) Index','1HZ100V':'Volatility 100 (1s) Index'};
  return m[s] || clean(s,60) || 'Digit Match';
}
async function verify(token, accountId){
  const r=await fetch('https://api.derivws.com/trading/v1/options/accounts',{headers:{Authorization:`Bearer ${token}`}});
  const d=await r.json().catch(()=>({}));
  if(!r.ok) throw Object.assign(new Error('Could not verify Deriv account'),{status:401});
  const a=Array.isArray(d?.data)?d.data:(d?.data?[d.data]:[]);
  const account=a.find(x=>String(x?.account_id||'')===String(accountId));
  if(!account) throw Object.assign(new Error('Selected Deriv account was not verified'),{status:403});
  return account;
}
function allowed(id){
  const list=String(process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS||'').split(',').map(x=>x.trim()).filter(Boolean);
  return list.length>0 && list.includes(String(id));
}
function normalise(c){
  if(!c||typeof c!=='object') throw new Error('Missing cycle');
  const trades=Array.isArray(c.trades)?c.trades.slice(0,200):[];
  return {
    id:clean(c.id,100),symbol:clean(c.symbol,40),digit:Number(c.digit),status:String(c.status||'').toUpperCase()==='WIN'?'WIN':'STOPPED',
    finalReason:clean(c.finalReason,200),winningTradeNumber:Number(c.winningTradeNumber||0)||null,totalInvestment:Number(c.totalInvestment||0),
    totalPayout:Number(c.totalPayout||0),netPnL:Number(c.netPnL||0),maxStake:Number(c.maxStake||0),trades
  };
}
function caption(c,type){
  const win=c.status==='WIN', n=c.trades.length, account=type==='REAL'?'REAL ACCOUNT':'DEMO ACCOUNT';
  const pnl=cash(c.netPnL);

  if(win){
    return [
      `⭐ <b>DIGITMATCHSTAR — ${account}</b>`,'',
      `📈 <b>${market(c.symbol)}</b>`,
      `🎯 Target digit: <b>${Number.isFinite(c.digit)?c.digit:'-'}</b>`,
      `✅ <b>MATCHED AT TRADE ${c.winningTradeNumber||n}</b>`,
      `🟢 <b>PROFIT: ${pnl}</b>`,
      `💵 Total stake: <b>$${c.totalInvestment.toFixed(2)}</b>`,'',
      type==='REAL'?'Real-money result. Trading involves risk.':'Demo result using virtual funds.',
      '⚠️ <b>Start on Demo to understand how DigitMatchStar works, how cycles behave, and how the risk controls operate before considering real-money use.</b>',
      'Trading involves risk, and past results do not guarantee future performance.','',
      'ℹ️ <b>Affiliate disclosure:</b> DigitMatchStar participates in the Deriv affiliate/partner programme and may earn a commission when eligible users register or trade through our partner links.','',
      '🚀 <b>Experience DigitMatchStar</b>',WEBSITE
    ].join('\n');
  }

  return [
    `⭐ <b>DIGITMATCHSTAR — ${account}</b>`,'',
    `📈 <b>${market(c.symbol)}</b>`,
    `🎯 Target digit: <b>${Number.isFinite(c.digit)?c.digit:'-'}</b>`,
    `🛑 <b>CYCLE STOPPED AFTER ${n} TRADE${n===1?'':'S'}</b>`,
    `🔴 <b>Cycle P/L: ${pnl}</b>`,
    `💵 Total stake: <b>$${c.totalInvestment.toFixed(2)}</b>`,'',
    `The selected digit did not match within the configured trade limit.`,
    `The bot stopped at the selected risk limit; no additional live contracts were placed.`,'',
    '⚠️ <b>Use Demo first to understand how DigitMatchStar works, how cycles behave, and how the risk controls operate before considering real-money use.</b>',
    'Choose limits you can afford to lose. Trading involves risk, and past results do not guarantee future performance.','',
    'ℹ️ <b>Affiliate disclosure:</b> DigitMatchStar participates in the Deriv affiliate/partner programme and may earn a commission when eligible users register or trade through our partner links.','',
    '🚀 <b>Experience DigitMatchStar</b>',WEBSITE
  ].join('\n');
}

function envStatus(){
  return {
    TELEGRAM_BOT_TOKEN: Boolean(String(process.env.TELEGRAM_BOT_TOKEN || '').trim()),
    TELEGRAM_ADMIN_CHAT_ID: Boolean(String(process.env.TELEGRAM_ADMIN_CHAT_ID || '').trim()),
    TELEGRAM_CHAT_ID: Boolean(String(process.env.TELEGRAM_CHAT_ID || '').trim()),
    TELEGRAM_APPROVER_USER_IDS: Boolean(String(process.env.TELEGRAM_APPROVER_USER_IDS || '').trim()),
    TELEGRAM_PUBLISH_ACCOUNT_IDS: Boolean(String(process.env.TELEGRAM_PUBLISH_ACCOUNT_IDS || '').trim())
  };
}

async function sendApprovalPreview(text){
  const token=String(process.env.TELEGRAM_BOT_TOKEN || '').trim();
  const adminChat=String(process.env.TELEGRAM_ADMIN_CHAT_ID || '').trim();

  if(!token){
    const e=new Error('TELEGRAM_BOT_TOKEN is missing in this deployment');
    e.status=500; throw e;
  }
  if(!adminChat){
    const e=new Error('TELEGRAM_ADMIN_CHAT_ID is missing in this deployment');
    e.status=500; throw e;
  }

  // Send the private review note as a SEPARATE message.
  // It will never be copied to the public channel.
  const noteResponse=await fetch(`https://api.telegram.org/bot${token}/sendMessage`,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      chat_id:adminChat,
      text:'🧾 <b>DigitMatchStar approval preview</b>\nReview the result below before it is posted publicly.',
      parse_mode:'HTML',
      disable_web_page_preview:true
    })
  });

  const noteData=await noteResponse.json().catch(()=>({}));
  if(!noteResponse.ok||!noteData?.ok){
    const e=new Error(`Telegram approval note failed: ${noteData?.description || `HTTP ${noteResponse.status}`}`);
    e.status=502; throw e;
  }

  // Send the actual result as its own message with approval buttons.
  // The approval endpoint copies THIS message only, so the private review note
  // never appears in the public channel.
  const resultResponse=await fetch(`https://api.telegram.org/bot${token}/sendMessage`,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      chat_id:adminChat,
      text,
      parse_mode:'HTML',
      disable_web_page_preview:true,
      reply_markup:{
        inline_keyboard:[
          [
            {text:'✅ APPROVE & PUBLISH',callback_data:'dms:approve'},
            {text:'❌ REJECT',callback_data:'dms:reject'}
          ],
          [{text:'🚀 Open DigitMatchStar',url:WEBSITE}]
        ]
      }
    })
  });

  const resultData=await resultResponse.json().catch(()=>({}));
  if(!resultResponse.ok||!resultData?.ok){
    const e=new Error(`Telegram approval preview failed: ${resultData?.description || `HTTP ${resultResponse.status}`}`);
    e.status=502; throw e;
  }

  return resultData.result;
}

module.exports=async function handler(req,res){
  // Safe diagnostic: reveals only whether required variables exist, never their values.
  if(req.method==='GET'){
    return res.status(200).json({ok:true,environment:envStatus()});
  }

  if(req.method!=='POST'){
    res.setHeader('Allow','GET, POST');
    return res.status(405).json({error:'method_not_allowed'});
  }

  try{
    const auth=String(req.headers.authorization||'');
    const token=auth.startsWith('Bearer ')?auth.slice(7).trim():'';
    if(!token) return res.status(401).json({error:'Missing Deriv bearer token'});

    const accountId=String(req.body?.account_id||'').trim();
    const account=await verify(token,accountId);

    if(!allowed(accountId)){
      return res.status(403).json({error:'This account is not authorized to publish to the official channel'});
    }

    const c=normalise(req.body?.cycle);
    if(!c.id||!c.trades.length) return res.status(400).json({error:'Invalid or empty cycle'});

    const type=String(account?.account_type||'').toLowerCase()==='real'?'REAL':'DEMO';
    const text=caption(c,type);

    const preview=await sendApprovalPreview(text);

    return res.status(200).json({
      published:false,
      pendingApproval:true,
      format:'text',
      accountType:type,
      cycleId:c.id,
      approvalMessageId:preview?.message_id||null
    });
  }catch(e){
    return res.status(e.status||500).json({
      error:e.message||'Publisher error',
      environment:envStatus()
    });
  }
};
