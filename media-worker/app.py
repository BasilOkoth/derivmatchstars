import shutil

import os, json, wave, math, hmac, hashlib, base64, tempfile, subprocess, re, gc, html
from pathlib import Path
from datetime import datetime, timezone
from array import array

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import imageio_ffmpeg

app = FastAPI(title="DigitMatchStar Premium Guided Media Worker v5.4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.digitmatchstar.com",
        "https://digitmatchstar.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

BASE_DIR = Path(__file__).resolve().parent
PENDING_DIR = BASE_DIR / "pending_moderation"
PENDING_DIR.mkdir(exist_ok=True)

W, H = 1080, 1920
BG = (5, 13, 9)
WHITE = (247, 250, 248)
MUTED = (150, 170, 159)
GREEN2 = (74, 222, 128)
RED = (239, 68, 68)
GOLD = (215, 181, 109)
CYAN = (34, 211, 238)
LINE = (43, 73, 57)

# Screen gets more real estate now; status is more compact.
SCREEN = dict(x=18, y=188, w=1044, h=760)
STATUS = dict(x=42, y=978, w=996, h=154)
PROGRESS = dict(x=42, y=1148, w=996, h=144)
METRIC_TOP = 1314
METRIC_BOTTOM = 1516

X264 = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "18",
    "-profile:v", "high",
    "-pix_fmt", "yuv420p",
    "-threads", "2",
    "-x264-params", "ref=1:bframes=0:rc-lookahead=0:sync-lookahead=0",
]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def secret_bytes() -> bytes:
    return env("MEDIA_WORKER_SECRET", "").encode()


def font(size: int, bold: bool=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def center(d, value, y, ff, fill=WHITE):
    value = str(value)
    b = d.textbbox((0,0), value, font=ff)
    d.text(((W - (b[2]-b[0]))/2, y), value, font=ff, fill=fill)


def right(d, value, x, y, ff, fill=WHITE):
    value = str(value)
    b = d.textbbox((0,0), value, font=ff)
    d.text((x-(b[2]-b[0]), y), value, font=ff, fill=fill)


def fit_font(d, value, max_width, start=36, minimum=15, bold=True):
    value = str(value)
    for size in range(start, minimum-1, -1):
        ff = font(size, bold)
        b = d.textbbox((0,0), value, font=ff)
        if b[2]-b[0] <= max_width:
            return ff
    return font(minimum, bold)


def money(value):
    try:
        n = float(value or 0)
    except Exception:
        n = 0.0
    return f"{'+' if n >= 0 else '-'}${abs(n):.2f}"


def plain_money(value):
    try:
        return f"${float(value or 0):,.2f}"
    except Exception:
        return "$0.00"


def sign_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(secret_bytes(), body.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{body}.{sig}"


def decode_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(secret_bytes(), body.encode(), hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(sig + "=" * ((4-len(sig)%4)%4))
        if not hmac.compare_digest(expected, got):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * ((4-len(body)%4)%4)))
        now = int(datetime.now(timezone.utc).timestamp())
        if int(payload.get("exp", 0)) < now:
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired token")


def decode_ticket(token: str):
    payload = decode_token(token)
    if payload.get("kind") not in {None, "capture"}:
        raise HTTPException(status_code=403, detail="Invalid live-capture ticket")
    return payload


def safe_json(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cycle JSON")


def run_ffmpeg(cmd, stage: str):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[FFMPEG:{stage}] FAILED rc={r.returncode}", flush=True)
        print((r.stderr or "")[-12000:], flush=True)
        raise RuntimeError(f"FFmpeg failed at stage: {stage}")
    return r


def probe_media(ffmpeg: str, media: Path):
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(media)], capture_output=True, text=True)
    txt = (r.stderr or "") + "\n" + (r.stdout or "")
    duration = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        hh, mm, ss = m.groups()
        duration = int(hh)*3600 + int(mm)*60 + float(ss)
    has_audio = bool(re.search(r"Stream #.*Audio:", txt))
    return duration, has_audio


def build_intro(cycle, account_type, out):
    im = Image.new("RGB", (W,H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((-280,-250,560,570), fill=(7,48,29))
    d.ellipse((760,-20,1360,650), fill=(48,39,13))
    center(d, "DIGITMATCHSTAR", 330, font(72,True), GREEN2)
    center(d, "TRADING IN PROGRESS", 445, font(48,True), WHITE)
    center(d, "Premium guided capture", 525, font(28,True), MUTED)

    acct = "REAL ACCOUNT" if account_type == "REAL" else "DEMO ACCOUNT"
    market = str(cycle.get("marketName") or cycle.get("symbol") or "Digit Match")
    digit = str(cycle.get("digit") or cycle.get("targetDigit") or "-")

    d.rounded_rectangle((170,690,910,970), radius=46, fill=(10,25,18), outline=LINE, width=3)
    center(d, acct, 758, font(30,True), GOLD if account_type == "REAL" else GREEN2)
    center(d, market, 835, font(32,True), WHITE)
    center(d, f"Target digit {digit}", 905, font(30,True), CYAN)

    center(d, "Real bot interface · guided status · live bot audio", 1230, font(28,True), WHITE)
    center(d, "Trading involves risk.", 1495, font(21), MUTED)
    im.save(out)


def build_outro_frame(cycle, website, typed_site, out):
    im = Image.new("RGB", (W,H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((-250,-220,530,560), fill=(8,50,30))
    win = str(cycle.get("status") or "").upper() == "WIN"
    n = len(cycle.get("trades") or [])
    center(d, "CYCLE COMPLETE", 260, font(36,True), MUTED)
    center(d, "DIGIT MATCHED" if win else "CYCLE STOPPED", 370, font(76,True), GREEN2 if win else RED)
    if win:
        center(d, f"TRADE {cycle.get('winningTradeNumber') or n}", 485, font(46,True), WHITE)
    center(d, money(cycle.get("netPnL",0)), 630, font(102,True), GREEN2 if float(cycle.get("netPnL",0) or 0) >= 0 else RED)

    cta1 = env("CTA_LINE_1", "Follow for more guided trading content")
    cta2 = env("CTA_LINE_2", "Watch, learn, then demo first")
    cta3 = env("CTA_LINE_3", "Educational content only · Trade responsibly")
    center(d, cta1, 900, font(36,True), WHITE)
    center(d, cta2, 970, font(30,True), CYAN)
    center(d, cta3, 1032, font(22), MUTED)

    # Website CTA with typewriter effect.
    d.rounded_rectangle((210, 1130, 870, 1288), radius=42, fill=(12,40,26), outline=(74,222,128), width=3)
    center(d, "VISIT DIGITMATCHSTAR", 1166, font(28,True), WHITE)

    # Animated typing line: caller renders a sequence of partial strings.
    shown = typed_site if typed_site else ""
    cursor = "▌"
    site_line = shown + cursor
    ff = fit_font(d, site_line, 580, start=34, minimum=22, bold=True)
    center(d, site_line, 1220, ff, GREEN2)

    center(d, "No guaranteed returns. Past results do not guarantee future performance.", 1498, font(20), MUTED)
    im.save(out)


def build_outro(cycle, website, out):
    # Compatibility: write final completed URL frame.
    site_label = website.replace("https://","").replace("http://","").rstrip("/")
    build_outro_frame(cycle, website, site_label, out)


def build_typed_outro(ffmpeg, cycle, website, td, out):
    """
    Build a typewriter-style website CTA.
    The URL appears character-by-character, then holds completed.
    """
    site_label = website.replace("https://","").replace("http://","").rstrip("/")
    if not site_label:
        site_label = "www.digitmatchstar.com"

    # Keep the animation readable and not too slow.
    total_type_time = 1.05
    hold_time = 0.75
    min_step = 0.035
    step = max(min_step, total_type_time / max(1, len(site_label)))

    clips = []
    # Use grouped characters for long URLs to avoid creating dozens of tiny clips.
    approx_frames = min(len(site_label), 22)
    for i in range(1, approx_frames + 1):
        chars = max(1, round(len(site_label) * i / approx_frames))
        partial = site_label[:chars]
        png = td / f"outro_type_{i:02d}.png"
        mp4 = td / f"outro_type_{i:02d}.mp4"
        build_outro_frame(cycle, website, partial, png)
        image_clip(ffmpeg, png, step, mp4)
        clips.append(mp4)

    # Final hold without blinking complexity: completed URL + cursor.
    final_png = td / "outro_type_final.png"
    final_mp4 = td / "outro_type_final.mp4"
    build_outro_frame(cycle, website, site_label, final_png)
    image_clip(ffmpeg, final_png, hold_time, final_mp4)
    clips.append(final_mp4)

    concat = td / "outro_type_concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips))
    run_ffmpeg([
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c", "copy", "-movflags", "+faststart", str(out)
    ], "typed-outro")

    return approx_frames * step + hold_time


def default_event(cycle):
    digit = cycle.get("digit") or cycle.get("targetDigit") or "-"
    return {
        "type":"capture_ready",
        "title":"TRADING SCREEN READY",
        "subtitle":f"Target digit {digit}",
        "atMs":0,
        "targetDigit":digit,
        "tradeCount":0,
        "stake":cycle.get("baseStake", cycle.get("stake", 0)),
        "pnl":0,
    }


def guided_segments(cycle, raw_duration):
    events = cycle.get("captureEvents") or []
    rows = []
    for e in events:
        try:
            at = max(0.0, float(e.get("atMs", 0))/1000.0)
        except Exception:
            continue
        if raw_duration is not None:
            at = min(at, raw_duration)
        rows.append({**e, "_at":at})
    rows.sort(key=lambda x: x["_at"])

    if not rows:
        rows = [default_event(cycle)]
        rows[0]["_at"] = 0.0

    compact = []
    for e in rows:
        key = (
            str(e.get("title","")),
            str(e.get("subtitle","")),
            int(e.get("tradeCount") or 0),
            str(e.get("targetDigit",""))
        )
        if compact and compact[-1]["_key"] == key:
            continue
        compact.append({**e, "_key":key})

    duration = raw_duration if raw_duration and raw_duration > 0.2 else max(10.0, compact[-1]["_at"] + 2.0)
    segments = []
    for i, e in enumerate(compact):
        start = e["_at"]
        end = compact[i+1]["_at"] if i+1 < len(compact) else duration
        if end <= start:
            end = min(duration, start + 0.25)
        if end - start < 0.08:
            continue
        segments.append({
            "start":start,
            "end":end,
            "duration":end-start,
            "event":e
        })

    if not segments:
        segments = [{"start":0.0,"end":duration,"duration":duration,"event":default_event(cycle)}]

    return segments, duration


def progress_state(cycle, event):
    trades = cycle.get("trades") or []
    current = int(event.get("tradeCount") or 0)
    event_type = str(event.get("type") or "")
    states = []
    for i in range(max(10, min(12, max(len(trades), current)))):
        trade_no = i + 1
        if trade_no < current:
            result = str((trades[i] if i < len(trades) else {}).get("result") or "LOSS").upper()
            states.append("win" if result == "WIN" else "loss")
        elif trade_no == current and current > 0:
            if event_type in {"matched","cycle_win","win_confirmed"}:
                states.append("win")
            elif event_type in {"loss_confirmed"}:
                states.append("loss")
            else:
                states.append("active")
        else:
            states.append("pending")
    return states


def build_live_frame(cycle, account_type, website, event, out):
    im = Image.new("RGB", (W,H), BG)
    d = ImageDraw.Draw(im)

    d.ellipse((-240,-200,480,510), fill=(6,43,26))
    d.ellipse((780,-30,1370,620), fill=(48,38,12))
    d.rounded_rectangle((24,24,1056,1896), radius=44, outline=(24,52,37), width=2)

    d.rounded_rectangle((28,28,1052,156), radius=30, fill=(9,22,16), outline=LINE, width=2)
    d.text((52,54), "DIGITMATCHSTAR", font=font(44,True), fill=GREEN2)
    d.text((52,104), "TRADING IN PROGRESS", font=font(24,True), fill=WHITE)

    target = event.get("targetDigit")
    if target is None:
        target = cycle.get("digit") or cycle.get("targetDigit") or "-"
    market = str(cycle.get("marketName") or cycle.get("symbol") or "Digit Match")
    acct = "REAL" if account_type == "REAL" else "DEMO"

    def chip(x,y,w,h,label,color):
        d.rounded_rectangle((x,y,x+w,y+h), radius=16, fill=(12,29,22), outline=LINE, width=1)
        ff = fit_font(d, label, w-22, start=18, minimum=13, bold=True)
        bb = d.textbbox((0,0), str(label), font=ff)
        d.text((x+(w-(bb[2]-bb[0]))/2, y+(h-(bb[3]-bb[1]))/2-1), str(label), font=ff, fill=color)

    chip(656,54,120,42,acct,GOLD if account_type=="REAL" else GREEN2)
    chip(788,54,242,42,f"TARGET {target}",CYAN)
    chip(656,104,374,38,market[:32],WHITE)

    # Browser-like screen template: larger and visually closer
    x,y,w,h = SCREEN["x"],SCREEN["y"],SCREEN["w"],SCREEN["h"]
    d.rounded_rectangle((x-6,y-6,x+w+6,y+h+6), radius=32, fill=(3,8,5), outline=(54,92,71), width=3)
    d.rounded_rectangle((x,y,x+w,y+h), radius=28, fill=(13,19,30), outline=(36,49,62), width=2)
    d.rounded_rectangle((x+14,y+14,x+w-14,y+58), radius=16, fill=(19,26,39), outline=(46,60,78), width=1)
    for idx,c in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        cx = x+32+idx*27
        d.ellipse((cx,y+26,cx+14,y+40),fill=c)
    d.rounded_rectangle((x+124,y+18,x+w-26,y+52), radius=14, fill=(9,18,29), outline=(48,63,83), width=1)
    d.text((x+146,y+25),"digitmatchstar.com",font=font(17,True),fill=(220,235,228))
    d.rounded_rectangle((x+w-110,y+18,x+w-32,y+50), radius=12, fill=(17,55,35), outline=(44,116,74), width=1)
    d.text((x+w-90,y+25),"LIVE",font=font(15,True),fill=GREEN2)

    # Status panel
    sx,sy,sw,sh = STATUS["x"],STATUS["y"],STATUS["w"],STATUS["h"]
    d.rounded_rectangle((sx,sy,sx+sw,sy+sh), radius=24, fill=(8,19,14), outline=LINE, width=2)
    title = str(event.get("title") or "TRADING IN PROGRESS")
    subtitle = str(event.get("subtitle") or "")
    etype = str(event.get("type") or "").lower()
    accent = GREEN2
    if "loss" in etype or "stop" in etype:
        accent = RED
    elif "entry" in etype or "recovery" in etype:
        accent = GOLD
    elif "scan" in etype or "verify" in etype:
        accent = CYAN

    d.text((sx+24,sy+16),"BOT STATUS",font=font(18,True),fill=MUTED)
    d.ellipse((sx+24,sy+58,sx+42,sy+76),fill=accent)
    title_ff = fit_font(d,title,sw-80,start=32,minimum=18,bold=True)
    d.text((sx+56,sy+46),title,font=title_ff,fill=accent)
    sub_ff = fit_font(d,subtitle,sw-80,start=20,minimum=14,bold=False)
    d.text((sx+56,sy+96),subtitle[:100],font=sub_ff,fill=(218,229,223))

    # Progress
    px,py,pw,ph = PROGRESS["x"],PROGRESS["y"],PROGRESS["w"],PROGRESS["h"]
    d.rounded_rectangle((px,py,px+pw,py+ph), radius=24, fill=(8,19,14), outline=LINE, width=2)
    d.text((px+24,py+14),"TRADE PROGRESS",font=font(18,True),fill=WHITE)
    states = progress_state(cycle,event)
    box_w = 64
    gap = 14
    total_w = len(states)*box_w + (len(states)-1)*gap
    start_x = px + (pw-total_w)/2
    by = py+60
    for i,s in enumerate(states):
        bx = start_x + i*(box_w+gap)
        col = {
            "pending":(28,44,35),
            "active":(245,158,11),
            "loss":RED,
            "win":GREEN2
        }[s]
        d.rounded_rectangle((bx,by,bx+box_w,by+42), radius=12, fill=col, outline=(68,90,76), width=1)
        ff = font(18,True)
        label = str(i+1)
        bb=d.textbbox((0,0),label,font=ff)
        d.text((bx+(box_w-(bb[2]-bb[0]))/2,by+9),label,font=ff,fill=WHITE)

    # Live metrics from event snapshot
    pnl = event.get("pnl",0)
    stake = event.get("stake",0)
    count = int(event.get("tradeCount") or 0)
    xs=[42,382,722]
    labels=["CYCLE P/L","CURRENT STAKE","TRADES"]
    values=[money(pnl),plain_money(stake),str(count)]
    colors=[GREEN2 if float(pnl or 0)>=0 else RED,WHITE,WHITE]
    sizes=[48,44,58]
    for i in range(3):
        cx=xs[i]
        d.rounded_rectangle((cx,METRIC_TOP,cx+296,METRIC_BOTTOM),radius=24,fill=(10,24,18),outline=LINE,width=2)
        d.text((cx+22,METRIC_TOP+18),labels[i],font=font(18,True),fill=MUTED)
        d.text((cx+22,METRIC_TOP+74),values[i],font=font(sizes[i],True),fill=colors[i])

    # Useful market strip
    current_digit = event.get("currentDigit")
    current_tick = str(event.get("currentTick") or "")
    d.rounded_rectangle((42,1540,1038,1634), radius=24, fill=(8,19,14), outline=LINE, width=2)
    market_text = f"Current digit: {current_digit if current_digit is not None else '-'}"
    if current_tick:
        market_text += f"  ·  Tick {current_tick}"
    d.text((68,1570), market_text, font=fit_font(d, market_text, 920, start=30, minimum=18, bold=True), fill=WHITE)

    d.text((46,1688),"Educational content only · not financial advice",font=font(18),fill=MUTED)
    right(d,website.replace("https://",""),1034,1688,font(18,True),GREEN2)
    center(d,"No guaranteed returns. Past results do not guarantee future performance.",1746,font(17),MUTED)

    # Slight sharpening to keep overlay crisp.
    im = im.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))
    im.save(out)


def image_clip(ffmpeg, image, duration, out):
    duration=max(0.08,float(duration))
    run_ffmpeg([
        ffmpeg,"-y","-loop","1","-t",f"{duration:.3f}","-i",str(image),
        "-vf","fps=30,format=yuv420p",
        *X264,"-movflags","+faststart","-an",str(out)
    ],f"image:{image.name}")


def build_layout_timeline(ffmpeg, cycle, account_type, website, raw_duration, td):
    segments, duration = guided_segments(cycle,raw_duration)
    clips=[]
    for i,seg in enumerate(segments):
        png=td/f"guided_{i:03d}.png"
        mp4=td/f"guided_{i:03d}.mp4"
        build_live_frame(cycle,account_type,website,seg["event"],png)
        image_clip(ffmpeg,png,seg["duration"],mp4)
        clips.append(mp4)

    concat=td/"layout_concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips))
    layout=td/"layout.mp4"
    run_ffmpeg([
        ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat),
        "-c","copy","-movflags","+faststart",str(layout)
    ],"layout-concat")
    return layout,duration


def build_live_video(ffmpeg, raw, layout, out):
    # Larger inner viewport with slight unsharp to improve clarity, still no crop.
    ix=SCREEN["x"]+18
    iy=SCREEN["y"]+70
    iw=SCREEN["w"]-36
    ih=SCREEN["h"]-88

    ratio=f"{iw}/{ih}"
    filter_complex=(
        f"[0:v]scale='if(gt(a,{ratio}),{iw},-2)':'if(gt(a,{ratio}),-2,{ih})',setsar=1,"
        f"pad={iw}:{ih}:(ow-iw)/2:(oh-ih)/2:color=0x05090d,"
        f"unsharp=5:5:0.8:3:3:0.4[screen];"
        f"[1:v][screen]overlay={ix}:{iy}:shortest=1,fps=30,format=yuv420p[outv]"
    )

    run_ffmpeg([
        ffmpeg,"-y","-i",str(raw),"-i",str(layout),
        "-filter_complex",filter_complex,
        "-map","[outv]",*X264,"-movflags","+faststart","-an",str(out)
    ],"full-screen-guided")


def build_focus_replay(ffmpeg, raw, cycle, account_type, website, duration, td, out):
    event=(cycle.get("captureEvents") or [default_event(cycle)])[-1]
    frame=td/"focus_frame.png"
    event={**event,"title":"FOCUS REPLAY","subtitle":"Rewatching the final trading moment"}
    build_live_frame(cycle,account_type,website,event,frame)

    replay_duration=min(1.6,max(0.8,duration))
    start=max(0.0,duration-replay_duration)

    ix=SCREEN["x"]+18
    iy=SCREEN["y"]+70
    iw=SCREEN["w"]-36
    ih=SCREEN["h"]-88
    ratio=f"{iw}/{ih}"
    filter_complex=(
        f"[0:v]scale='if(gt(a,{ratio}),{iw},-2)':'if(gt(a,{ratio}),-2,{ih})',setsar=1,"
        f"pad={iw}:{ih}:(ow-iw)/2:(oh-ih)/2:color=0x05090d,"
        f"unsharp=5:5:0.8:3:3:0.4[screen];"
        f"[1:v][screen]overlay={ix}:{iy}:shortest=1,fps=30,format=yuv420p[outv]"
    )
    run_ffmpeg([
        ffmpeg,"-y","-ss",f"{start:.3f}","-t",f"{replay_duration:.3f}","-i",str(raw),
        "-loop","1","-i",str(frame),
        "-filter_complex",filter_complex,
        "-map","[outv]",*X264,"-movflags","+faststart","-an",str(out)
    ],"focus-replay")
    return replay_duration


def build_soundtrack(total_duration, live_start, live_end, is_win, out):
    sr=32000
    samples=max(1,int(total_duration*sr))
    data=array("h",[0])*samples

    def add_tone(start,dur,freq,amp=0.08):
        a=max(0,int(start*sr))
        b=min(samples,int((start+dur)*sr))
        peak=int(32767*amp)
        for i in range(a,b):
            t=(i-a)/sr
            env=min(1.0,t/0.02)*min(1.0,max(0.0,(dur-t)/0.04))
            val=data[i]+int(peak*env*math.sin(2*math.pi*freq*t))
            data[i]=max(-32768,min(32767,val))

    add_tone(0.12,0.12,440,0.06)
    add_tone(0.34,0.14,660,0.06)

    t=live_start+0.5
    while t<live_end-0.3:
        add_tone(t,0.030,1400,0.018)
        t+=1.0

    if is_win:
        add_tone(live_end-0.02,0.12,740,0.09)
        add_tone(live_end+0.12,0.16,988,0.09)

    with wave.open(str(out),"wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        chunk=16000
        for i in range(0,len(data),chunk):
            wf.writeframes(data[i:i+chunk].tobytes())
    del data


def compose_guided(raw,cycle,account_type,website,out):
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as t:
        td=Path(t)

        raw_duration,raw_has_audio=probe_media(ffmpeg,raw)
        if not raw_duration:
            events=cycle.get("captureEvents") or []
            if events:
                raw_duration=max(3.0,max(float(e.get("atMs",0) or 0) for e in events)/1000.0+2.0)
            else:
                raw_duration=12.0

        intro_png=td/"intro.png"
        build_intro(cycle,account_type,intro_png)

        intro=td/"intro.mp4"
        outro=td/"outro.mp4"
        image_clip(ffmpeg,intro_png,0.75,intro)
        outro_duration = build_typed_outro(ffmpeg, cycle, website, td, outro)

        layout,duration=build_layout_timeline(ffmpeg,cycle,account_type,website,raw_duration,td)
        live=td/"live.mp4"
        build_live_video(ffmpeg,raw,layout,live)

        focus=td/"focus.mp4"
        focus_duration=build_focus_replay(ffmpeg,raw,cycle,account_type,website,duration,td,focus)

        concat=td/"all.txt"
        concat.write_text(
            f"file '{intro.as_posix()}'\n"
            f"file '{live.as_posix()}'\n"
            f"file '{focus.as_posix()}'\n"
            f"file '{outro.as_posix()}'\n"
        )
        silent=td/"silent.mp4"
        run_ffmpeg([
            ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat),
            "-c","copy","-movflags","+faststart",str(silent)
        ],"final-concat")

        total=0.75+duration+focus_duration+outro_duration
        sound=td/"sound.wav"
        build_soundtrack(total,0.75,0.75+duration+focus_duration,
                         str(cycle.get("status") or "").upper()=="WIN",sound)

        if raw_has_audio:
            run_ffmpeg([
                ffmpeg,"-y","-i",str(silent),"-i",str(sound),"-i",str(raw),
                "-filter_complex",
                "[1:a]volume=0.16[sfx];"
                "[2:a]adelay=750|750,volume=1.0[bot];"
                "[sfx][bot]amix=inputs=2:duration=longest:dropout_transition=1[aout]",
                "-map","0:v:0","-map","[aout]",
                "-c:v","copy","-c:a","aac","-b:a","160k",
                "-shortest","-movflags","+faststart",str(out)
            ],"audio-mix")
        else:
            run_ffmpeg([
                ffmpeg,"-y","-i",str(silent),"-i",str(sound),
                "-c:v","copy","-c:a","aac","-b:a","128k",
                "-shortest","-movflags","+faststart",str(out)
            ],"audio")

        gc.collect()


async def tg_request(method: str, data=None, files=None):
    token=env("TELEGRAM_BOT_TOKEN","")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    async with httpx.AsyncClient(timeout=300) as client:
        r=await client.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files)
        payload=r.json()
        if not r.is_success or not payload.get("ok"):
            raise RuntimeError(payload.get("description") or f"{method} failed")
        return payload["result"]


async def send_video(chat: str, video: Path, caption: str):
    with video.open("rb") as fh:
        return await tg_request(
            "sendVideo",
            data={
                "chat_id":chat,
                "caption":caption[:950],
                "parse_mode":"HTML",
                "supports_streaming":"true"
            },
            files={"video":(video.name,fh,"video/mp4")}
        )


async def send_message(chat: str, text: str):
    return await tg_request("sendMessage", data={"chat_id":chat, "text":text[:4000], "parse_mode":"HTML", "disable_web_page_preview":"true"})


def moderation_links(item_id: str):
    exp = int(datetime.now(timezone.utc).timestamp()) + 7*24*3600
    approve_token = sign_token({"kind":"moderate","action":"approve","item":item_id,"exp":exp})
    reject_token = sign_token({"kind":"moderate","action":"reject","item":item_id,"exp":exp})
    base = env("PUBLIC_BASE_URL", "https://digitmatchstar-media-worker.onrender.com").rstrip("/")
    return (
        f"{base}/moderate?t={approve_token}",
        f"{base}/moderate?t={reject_token}",
    )


def moderation_caption():
    return (
        "🎥 <b>DIGITMATCHSTAR PREMIUM GUIDED VIDEO</b>\n"
        "Preview pending moderation.\n"
        "Use the approve/reject links below."
    )


def public_caption():
    line1 = env("CTA_LINE_1", "Follow for more guided trading content")
    line2 = env("CTA_LINE_2", "Watch, learn, then demo first")
    site = env("PUBLIC_WEBSITE_URL", "https://www.digitmatchstar.com")
    risk = "Educational content only. Trading involves risk."
    return f"{line1}\n{line2}\nVisit: {site}\n{risk}"


def save_pending_item(item_id: str, video_path: Path, cycle: dict, website: str):
    item_dir = PENDING_DIR / item_id
    item_dir.mkdir(exist_ok=True)
    shutil_path = item_dir / "video.mp4"
    shutil_path.write_bytes(video_path.read_bytes())
    (item_dir / "meta.json").write_text(json.dumps({
        "id": item_id,
        "website": website,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "cycle": cycle,
        "status": "pending"
    }, ensure_ascii=False), encoding="utf-8")


def load_pending_item(item_id: str):
    item_dir = PENDING_DIR / item_id
    meta = item_dir / "meta.json"
    video = item_dir / "video.mp4"
    if not meta.exists() or not video.exists():
        raise HTTPException(status_code=404, detail="Pending item not found")
    data = json.loads(meta.read_text(encoding="utf-8"))
    return item_dir, data, video


def set_pending_status(item_dir: Path, data: dict, status: str):
    data["status"] = status
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    (item_dir / "meta.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@app.get("/")
def root():
    return {"ok":True,"version":"premium-guided-v5.4"}


@app.get("/health")
def health():
    return {
        "ok":True,
        "version":"premium-guided-v5.4",
        "cors":True,
        "telegramConfigured":bool(
            env("TELEGRAM_BOT_TOKEN") and
            env("TELEGRAM_ADMIN_CHAT_ID")
        ),
        "approvalConfigured":bool(env("MAIN_CHANNEL_CHAT_ID")),
    }


@app.get("/moderate", response_class=HTMLResponse)
async def moderate(t: str = Query(...)):
    payload = decode_token(t)
    if payload.get("kind") != "moderate":
        raise HTTPException(status_code=403, detail="Invalid moderation token")
    action = payload.get("action")
    item_id = str(payload.get("item") or "")
    if action not in {"approve", "reject"} or not item_id:
        raise HTTPException(status_code=400, detail="Invalid moderation request")

    item_dir, data, video = load_pending_item(item_id)

    if data.get("status") != "pending":
        return HTMLResponse(f"<h2>Already processed</h2><p>Item status: {html.escape(str(data.get('status')))}</p>")

    admin_chat = env("TELEGRAM_ADMIN_CHAT_ID", "")
    if action == "reject":
        set_pending_status(item_dir, data, "rejected")
        if admin_chat:
            await send_message(admin_chat, f"❌ Preview rejected\nID: <code>{item_id}</code>")
        return HTMLResponse("<h2>Rejected</h2><p>The preview was rejected and will not be posted.</p>")

    channel = env("MAIN_CHANNEL_CHAT_ID", "")
    if not channel:
        raise HTTPException(status_code=500, detail="MAIN_CHANNEL_CHAT_ID is missing")

    await send_video(channel, video, public_caption())
    set_pending_status(item_dir, data, "approved")
    if admin_chat:
        await send_message(admin_chat, f"✅ Preview approved and posted\nID: <code>{item_id}</code>")
    return HTMLResponse("<h2>Approved</h2><p>The video has been posted to the main channel.</p>")


@app.post("/compose-live")
async def compose_live_endpoint(
    video: UploadFile=File(...),
    ticket: str=Form(...),
    cycle: str=Form(...),
    website: str=Form("https://www.digitmatchstar.com")
):
    claims=decode_ticket(ticket)
    c=safe_json(cycle)

    if str(c.get("id") or "") != str(claims.get("cycleId") or ""):
        raise HTTPException(status_code=400,detail="Cycle id does not match upload ticket")

    admin=env("TELEGRAM_ADMIN_CHAT_ID","")
    if not admin:
        raise HTTPException(status_code=500,detail="TELEGRAM_ADMIN_CHAT_ID is missing")

    with tempfile.TemporaryDirectory() as t:
        td=Path(t)
        raw=td/"capture.webm"
        total=0
        with raw.open("wb") as out:
            while True:
                chunk=await video.read(1024*1024)
                if not chunk:
                    break
                total+=len(chunk)
                if total>180*1024*1024:
                    raise HTTPException(status_code=413,detail="Live capture is too large")
                out.write(chunk)

        c["marketName"]=c.get("marketName") or c.get("symbol") or "Digit Match"

        final=td/"digitmatchstar-premium-guided.mp4"
        compose_guided(raw,c,str(claims.get("accountType") or "DEMO"),website,final)

        item_id = f"{claims.get('cycleId')}-{int(datetime.now(timezone.utc).timestamp())}"
        save_pending_item(item_id, final, c, website)
        approve_url, reject_url = moderation_links(item_id)

        msg=await send_video(admin, final, moderation_caption())
        await send_message(
            admin,
            "Review this preview:\n"
            f"✅ Approve: {approve_url}\n"
            f"❌ Reject: {reject_url}\n\n"
            "Website CTA included: https://www.digitmatchstar.com\nSuggested CTA is non-promissory, educational, and risk-aware."
        )

    return {
        "ok":True,
        "privateTelegramMessageId":msg.get("message_id"),
        "format":"1080x1920-h264-aac",
        "source":"full-browser-capture",
        "version":"premium-guided-v5.4",
        "features":[
            "full-screen-preserved",
            "clearer-screen",
            "guided-status-timeline",
            "trade-progress",
            "live-metrics",
            "focus-replay",
            "bot-tab-audio",
            "approve-reject",
            "cta-outro",
            "telegram-delivery"
        ]
    }
