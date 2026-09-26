import os, tempfile, subprocess
from pathlib import Path
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

app=FastAPI(title="DigitMatchStar Media Worker")
W,H=1080,1920
BG=(7,18,13); PANEL=(17,35,26); WHITE=(247,250,248); MUTED=(157,177,166); GREEN=(34,197,94); RED=(239,68,68); GOLD=(215,181,109)

class Payload(BaseModel):
    accountType:str
    accountId:str|None=None
    cycle:dict
    caption:str
    website:str="https://www.digitmatchstar.com"

def f(size,bold=False):
    paths=[
      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
      "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for p in paths:
        if Path(p).exists(): return ImageFont.truetype(p,size=size)
    return ImageFont.load_default()

def center(d,t,y,ff,fill=WHITE):
    b=d.textbbox((0,0),t,font=ff); d.text(((W-(b[2]-b[0]))//2,y),t,font=ff,fill=fill)

def money(v):
    n=float(v or 0); return f"{'+' if n>=0 else '-'}${abs(n):.2f}"

def slide(p:Payload,i:int,branded:bool,path:Path):
    c=p.cycle; win=str(c.get("status","")).upper()=="WIN"; trades=c.get("trades") or []; n=len(trades)
    im=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(im)
    d.ellipse((-240,-180,460,520),fill=(10,52,31)); d.ellipse((760,80,1280,600),fill=(45,39,16))
    d.text((72,76),"DIGITMATCHSTAR" if branded else "DIGIT MATCH — LIVE CYCLE",font=f(46,True),fill=GREEN if branded else WHITE)
    d.rounded_rectangle((72,220,1008,420),radius=40,fill=(12,29,20),outline=(46,80,61),width=2)
    account="REAL ACCOUNT" if p.accountType.upper()=="REAL" else "DEMO ACCOUNT"
    d.text((116,264),account,font=f(26,True),fill=GOLD if p.accountType.upper()=="REAL" else GREEN)
    d.text((116,320),str(c.get("symbol","Digit Match")),font=f(34,True),fill=WHITE)
    if i==1:
        center(d,"TARGET DIGIT",560,f(28,True),MUTED); center(d,str(c.get("digit","-")),630,f(250,True),GREEN)
        center(d,"Cycle started",1010,f(42,True)); center(d,"Watch the result",1076,f(28),MUTED)
    elif i==2:
        center(d,"CYCLE RESULT",555,f(28,True),MUTED)
        result=f"MATCHED · TRADE {c.get('winningTradeNumber') or n}" if win else f"STOPPED · TRADE {n}"
        center(d,result,645,f(58,True),GREEN if win else RED)
        d.rounded_rectangle((118,820,962,1095),radius=34,fill=(12,29,20),outline=(46,80,61),width=2)
        d.text((170,868),"Cycle P/L",font=f(28),fill=MUTED); d.text((170,928),money(c.get("netPnL",0)),font=f(72,True),fill=GREEN if float(c.get("netPnL",0) or 0)>=0 else RED)
    else:
        center(d,"STRUCTURED. AUTOMATED. CONTROLLED.",600,f(40,True))
        center(d,f"{n} trades in this cycle",700,f(30),MUTED)
        if branded:
            center(d,"Experience DigitMatchStar",900,f(52,True),GREEN)
            center(d,p.website.replace("https://",""),990,f(34,True))
        else:
            center(d,"Result shown exactly as recorded",900,f(38,True))
        center(d,"Past results do not guarantee future performance.",1120,f(24),MUTED)
    d.line((72,1760,1008,1760),fill=(45,70,57),width=2); d.text((72,1790),"Recorded cycle result",font=f(22),fill=MUTED)
    im.save(path)

def render(p:Payload,branded:bool,out:Path):
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); slides=[]
        for i in (1,2,3):
            x=td/f"s{i}.png"; slide(p,i,branded,x); slides.append(x)
        lst=td/"concat.txt"
        lst.write_text("\n".join([f"file '{x.as_posix()}'\nduration 2.5" for x in slides]+[f"file '{slides[-1].as_posix()}'"]))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-f","concat","-safe","0","-i",str(lst),"-vf","fps=30,format=yuv420p","-c:v","libx264","-preset","veryfast","-movflags","+faststart",str(out)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

async def send(video:Path,caption:str,chat:str):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","")
    if not token or not chat: raise RuntimeError("Telegram worker environment is not configured")
    async with httpx.AsyncClient(timeout=90) as c:
        with video.open("rb") as fh:
            r=await c.post(f"https://api.telegram.org/bot{token}/sendVideo",data={"chat_id":chat,"caption":caption,"parse_mode":"HTML","supports_streaming":"true"},files={"video":(video.name,fh,"video/mp4")})
            d=r.json()
            if not r.is_success or not d.get("ok"): raise RuntimeError(d.get("description") or "sendVideo failed")

def auth(secret):
    if not os.environ.get("MEDIA_WORKER_SECRET") or secret!=os.environ.get("MEDIA_WORKER_SECRET"):
        raise HTTPException(status_code=403,detail="Forbidden")

@app.get("/health")
def health(): return {"ok":True}

@app.post("/publish")
async def publish(p:Payload,x_publisher_secret:str|None=Header(default=None)):
    auth(x_publisher_secret)
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        public=td/"digitmatchstar-result.mp4"; render(p,True,public)
        await send(public,p.caption,os.environ.get("TELEGRAM_CHAT_ID",""))
        admin=os.environ.get("TELEGRAM_ADMIN_CHAT_ID","")
        made=False
        if admin:
            clean=td/"tiktok-ready-result.mp4"; render(p,False,clean)
            await send(clean,"🎬 <b>TikTok-ready vertical export</b>\nReview before posting.",admin)
            made=True
    return {"published":True,"telegramVideo":True,"tiktokReadyCopy":made}
