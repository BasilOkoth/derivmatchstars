// /api/telegram-approval.js
// One-tap Share / Reject webhook for preview VIDEO messages.

function parseAllowedApprovers(){
  return String(
    process.env.TELEGRAM_APPROVER_USER_IDS || ''
  )
    .split(',')
    .map(x=>x.trim())
    .filter(Boolean);
}

function envStatus(){
  return {
    TELEGRAM_BOT_TOKEN:Boolean(String(process.env.TELEGRAM_BOT_TOKEN || '').trim()),
    TELEGRAM_CHAT_ID:Boolean(String(process.env.TELEGRAM_CHAT_ID || process.env.MAIN_CHANNEL_CHAT_ID || '').trim()),
    TELEGRAM_APPROVER_USER_IDS:Boolean(String(process.env.TELEGRAM_APPROVER_USER_IDS || '').trim()),
    TELEGRAM_WEBHOOK_SECRET:Boolean(String(process.env.TELEGRAM_WEBHOOK_SECRET || '').trim())
  };
}

async function tg(method, payload){
  const token=process.env.TELEGRAM_BOT_TOKEN;

  if(!token){
    throw new Error('TELEGRAM_BOT_TOKEN is missing');
  }

  const r=await fetch(
    `https://api.telegram.org/bot${token}/${method}`,
    {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    }
  );

  const d=await r.json().catch(()=>({}));

  if(!r.ok || !d?.ok){
    throw new Error(
      d?.description || `${method} failed`
    );
  }

  return d.result;
}

module.exports=async function handler(req,res){
  if(req.method==='GET'){
    return res.status(200).json({
      ok:true,
      version:'telegram-approval-v2.0',
      environment:envStatus()
    });
  }

  if(req.method!=='POST'){
    res.setHeader('Allow','GET, POST');
    return res.status(405).json({
      error:'method_not_allowed'
    });
  }

  try{
    const expectedSecret=String(
      process.env.TELEGRAM_WEBHOOK_SECRET || ''
    );

    if(expectedSecret){
      const got=String(
        req.headers['x-telegram-bot-api-secret-token'] || ''
      );

      if(got!==expectedSecret){
        return res.status(401).json({
          error:'invalid_webhook_secret'
        });
      }
    }

    const q=req.body?.callback_query;

    if(!q){
      return res.status(200).json({
        ok:true,
        ignored:true
      });
    }

    const action=String(q.data || '');

    if(
      action!=='dms:approve' &&
      action!=='dms:reject'
    ){
      await tg('answerCallbackQuery',{
        callback_query_id:q.id,
        text:'Unknown action'
      });

      return res.status(200).json({
        ok:true,
        ignored:true
      });
    }

    const fromId=String(q.from?.id || '');
    const approvers=parseAllowedApprovers();

    if(
      !approvers.length ||
      !approvers.includes(fromId)
    ){
      await tg('answerCallbackQuery',{
        callback_query_id:q.id,
        text:'You are not authorized to share DigitMatchStar posts.',
        show_alert:true
      });

      return res.status(403).json({
        error:'approver_not_authorized'
      });
    }

    const adminChatId=String(
      q.message?.chat?.id || ''
    );

    const messageId=Number(
      q.message?.message_id || 0
    );

    const publicChatId=String(
      process.env.TELEGRAM_CHAT_ID ||
      process.env.MAIN_CHANNEL_CHAT_ID ||
      ''
    );

    if(!adminChatId || !messageId){
      await tg('answerCallbackQuery',{
        callback_query_id:q.id,
        text:'Preview message not found',
        show_alert:true
      });

      return res.status(400).json({
        error:'missing_approval_message'
      });
    }

    if(action==='dms:approve'){
      if(!publicChatId){
        throw new Error(
          'TELEGRAM_CHAT_ID / MAIN_CHANNEL_CHAT_ID is missing'
        );
      }

      const copied=await tg('copyMessage',{
        chat_id:publicChatId,
        from_chat_id:adminChatId,
        message_id:messageId,
        reply_markup:{
          inline_keyboard:[
            [{
              text:'🚀 Open DigitMatchStar',
              url:
                process.env.DIGITMATCHSTAR_URL ||
                'https://www.digitmatchstar.com'
            }]
          ]
        }
      });

      await tg('editMessageReplyMarkup',{
        chat_id:adminChatId,
        message_id:messageId,
        reply_markup:{inline_keyboard:[]}
      });

      await tg('answerCallbackQuery',{
        callback_query_id:q.id,
        text:'Shared ✅'
      });

      return res.status(200).json({
        ok:true,
        action:'shared',
        publicMessageId:
          copied?.message_id||null
      });
    }

    await tg('editMessageReplyMarkup',{
      chat_id:adminChatId,
      message_id:messageId,
      reply_markup:{inline_keyboard:[]}
    });

    await tg('answerCallbackQuery',{
      callback_query_id:q.id,
      text:'Rejected'
    });

    return res.status(200).json({
      ok:true,
      action:'rejected'
    });

  }catch(e){
    console.error('[telegram-approval]',e);
    return res.status(500).json({
      error:
        e?.message ||
        'Telegram approval error',
      environment:envStatus()
    });
  }
};
