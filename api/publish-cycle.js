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
  return [
    `⭐ <b>DIGITMATCHSTAR — ${account}</b>`,'',
    `📈 <b>${market(c.symbol)}</b>`,
    `🎯 Target digit: <b>${Number.isFinite(c.digit)?c.digit:'-'}</b>`,
    win?`✅ <b>MATCHED AT TRADE ${c.winningTradeNumber||n}</b>`:`⛔ <b>CYCLE STOPPED AT TRADE ${n}</b>`,
    `💰 Cycle P/L: <b>${cash(c.netPnL)}</b>`,
    `💵 Total stake: <b>$${c.totalInvestment.toFixed(2)}</b>`,'',
    type==='REAL'?'Real-money result. Trading involves risk.':'Demo result using virtual funds.',
    'Past results do not guarantee future performance.','',
    '🚀 <b>Experience DigitMatchStar</b>',WEBSITE
  ].join('\n');
}
async function telegramText(text){
  const token=process.env.TELEGRAM_BOT_TOKEN, chat=process.env.TELEGRAM_CHAT_ID;
  if(!token||!chat) throw new Error('Telegram environment variables are missing');
  const r=await fetch(`https://api.telegram.org/bot${token}/sendMessage`,{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({chat_id:chat,text,parse_mode:'HTML',reply_markup:{inline_keyboard:[[{text:'🚀 Open DigitMatchStar',url:WEBSITE}]]}})
  });
  const d=await r.json().catch(()=>({}));
  if(!r.ok||!d?.ok) throw new Error(d?.description||'Telegram send failed');
}
async function mediaWorker(payload){
  const url=String(process.env.MEDIA_WORKER_URL||'').replace(/\/$/,'');
  const secret=process.env.MEDIA_WORKER_SECRET;
  if(!url||!secret) return {used:false};
  try{
    const r=await fetch(`${url}/publish`,{method:'POST',headers:{'Content-Type':'application/json','X-Publisher-Secret':secret},body:JSON.stringify(payload)});
    const d=await r.json().catch(()=>({}));
    return r.ok&&d?.published?{used:true,data:d}:{used:false,error:d?.detail||d?.error||`HTTP ${r.status}`};
  }catch(e){ return {used:false,error:e.message}; }
}
module.exports=async function handler(req,res){
  if(req.method!=='POST'){res.setHeader('Allow','POST');return res.status(405).json({error:'method_not_allowed'});}
  try{
    const auth=String(req.headers.authorization||'');
    const token=auth.startsWith('Bearer ')?auth.slice(7).trim():'';
    if(!token) return res.status(401).json({error:'Missing Deriv bearer token'});
    const accountId=String(req.body?.account_id||'').trim();
    const account=await verify(token,accountId);
    if(!allowed(accountId)) return res.status(403).json({error:'This account is not authorized to publish to the official channel'});
    const c=normalise(req.body?.cycle);
    if(!c.id||!c.trades.length) return res.status(400).json({error:'Invalid or empty cycle'});
    const type=String(account?.account_type||'').toLowerCase()==='real'?'REAL':'DEMO';
    const text=caption(c,type);
    const media=await mediaWorker({accountType:type,accountId,cycle:c,caption:text,website:WEBSITE});
    if(!media.used) await telegramText(text);
    return res.status(200).json({published:true,format:media.used?'video':'text',accountType:type,cycleId:c.id,mediaError:media.error||null});
  }catch(e){ return res.status(e.status||500).json({error:e.message||'Publisher error'}); }
};
