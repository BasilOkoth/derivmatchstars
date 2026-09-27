import os, json, wave, math, hmac, hashlib, base64, tempfile, subprocess, re, gc
from pathlib import Path
from datetime import datetime, timezone
from array import array

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

app = FastAPI(title="DigitMatchStar Premium Guided Media Worker v5.0")

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

W, H = 1080, 1920
BG = (5, 13, 9)
WHITE = (247, 250, 248)
MUTED = (150, 170, 159)
GREEN2 = (74, 222, 128)
RED = (239, 68, 68)
GOLD = (215, 181, 109)
CYAN = (34, 211, 238)
LINE = (43, 73, 57)

# Full screen is deliberately landscape within the portrait video.
# Nothing in the captured browser viewport is cropped.
SCREEN = dict(x=42, y=206, w=996, h=620)
STATUS = dict(x=42, y=852, w=996, h=190)
PROGRESS = dict(x=42, y=1068, w=996, h=164)
METRIC_TOP = 1258
METRIC_BOTTOM = 1496

X264 = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "20",
    "-profile:v", "high",
    "-pix_fmt", "yuv420p",
    "-threads", "2",
    "-x264-params", "ref=1:bframes=0:rc-lookahead=0:sync-lookahead=0",
]


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


def decode_ticket(token: str):
    try:
        body, sig = token.split(".", 1)
        secret = os.environ.get("MEDIA_WORKER_SECRET", "").encode()
        expected = hmac.new(secret, body.encode(), hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(sig + "=" * ((4-len(sig)%4)%4))
        if not hmac.compare_digest(expected, got):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * ((4-len(body)%4)%4)))
        now = int(datetime.now(timezone.utc).timestamp())
        if int(payload.get("exp", 0)) < now:
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired live-capture ticket")


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
    center(d, "Premium guided trading capture", 525, font(28,True), MUTED)

    acct = "REAL ACCOUNT" if account_type == "REAL" else "DEMO ACCOUNT"
    market = str(cycle.get("marketName") or cycle.get("symbol") or "Digit Match")
    digit = str(cycle.get("digit") or cycle.get("targetDigit") or "-")

    d.rounded_rectangle((170,690,910,970), radius=46, fill=(10,25,18), outline=LINE, width=3)
    center(d, acct, 758, font(30,True), GOLD if account_type == "REAL" else GREEN2)
    center(d, market, 835, font(32,True), WHITE)
    center(d, f"Target digit {digit}", 905, font(30,True), CYAN)

    center(d, "Full browser capture · guided status · real bot audio", 1230, font(28,True), WHITE)
    center(d, "Trading involves risk.", 1495, font(21), MUTED)
    im.save(out)


def build_outro(cycle, website, out):
    im = Image.new("RGB", (W,H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((-250,-220,530,560), fill=(8,50,30))
    win = str(cycle.get("status") or "").upper() == "WIN"
    n = len(cycle.get("trades") or [])
    center(d, "CYCLE COMPLETE", 320, font(38,True), MUTED)
    center(d, "DIGIT MATCHED" if win else "CYCLE STOPPED", 450, font(82,True), GREEN2 if win else RED)
    if win:
        center(d, f"TRADE {cycle.get('winningTradeNumber') or n}", 575, font(50,True), WHITE)
    center(d, money(cycle.get("netPnL",0)), 760, font(110,True), GREEN2 if float(cycle.get("netPnL",0) or 0) >= 0 else RED)
    center(d, website.replace("https://",""), 1115, font(42,True), GREEN2)
    center(d, "Past results do not guarantee future performance.", 1510, font(21), MUTED)
    im.save(out)


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

    # Remove near-identical adjacent statuses.
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

    # Header only. No "actual trading screen" label.
    d.rounded_rectangle((42,42,1038,176), radius=30, fill=(9,22,16), outline=LINE, width=2)
    d.text((68,66), "DIGITMATCHSTAR", font=font(43,True), fill=GREEN2)
    d.text((68,118), "TRADING IN PROGRESS", font=font(24,True), fill=WHITE)

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

    chip(660,60,120,42,acct,GOLD if account_type=="REAL" else GREEN2)
    chip(792,60,220,42,f"TARGET {target}",CYAN)
    chip(660,112,352,38,market[:30],WHITE)

    # Browser-like full screen template.
    x,y,w,h = SCREEN["x"],SCREEN["y"],SCREEN["w"],SCREEN["h"]
    d.rounded_rectangle((x-6,y-6,x+w+6,y+h+6), radius=32, fill=(3,8,5), outline=(54,92,71), width=3)
    d.rounded_rectangle((x,y,x+w,y+h), radius=28, fill=(13,19,30), outline=(36,49,62), width=2)
    d.rounded_rectangle((x+16,y+14,x+w-16,y+62), radius=18, fill=(19,26,39), outline=(46,60,78), width=1)
    for idx,c in enumerate([(255,95,86),(255,189,46),(39,201,63)]):
        cx = x+34+idx*27
        d.ellipse((cx,y+28,cx+14,y+42),fill=c)
    d.rounded_rectangle((x+126,y+20,x+w-28,y+56), radius=15, fill=(9,18,29), outline=(48,63,83), width=1)
    d.text((x+150,y+28),"digitmatchstar.com",font=font(18,True),fill=(220,235,228))
    d.rounded_rectangle((x+w-112,y+22,x+w-34,y+54), radius=13, fill=(17,55,35), outline=(44,116,74), width=1)
    d.text((x+w-92,y+30),"LIVE",font=font(16,True),fill=GREEN2)

    # Status panel
    sx,sy,sw,sh = STATUS["x"],STATUS["y"],STATUS["w"],STATUS["h"]
    d.rounded_rectangle((sx,sy,sx+sw,sy+sh), radius=28, fill=(8,19,14), outline=LINE, width=2)
    d.text((sx+28,sy+20),"BOT STATUS",font=font(20,True),fill=MUTED)

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

    d.ellipse((sx+28,sy+69,sx+48,sy+89),fill=accent)
    title_ff = fit_font(d,title,sw-120,start=30,minimum=18,bold=True)
    d.text((sx+64,sy+60),title,font=title_ff,fill=accent)
    sub_ff = fit_font(d,subtitle,sw-120,start=20,minimum=15,bold=False)
    d.text((sx+64,sy+112),subtitle[:100],font=sub_ff,fill=(218,229,223))

    # Progress
    px,py,pw,ph = PROGRESS["x"],PROGRESS["y"],PROGRESS["w"],PROGRESS["h"]
    d.rounded_rectangle((px,py,px+pw,py+ph), radius=28, fill=(8,19,14), outline=LINE, width=2)
    d.text((px+28,py+18),"TRADE PROGRESS",font=font(20,True),fill=WHITE)
    d.text((px+28,py+50),"Grey = pending · orange = active · red = miss · green = match",font=font(15),fill=MUTED)

    states = progress_state(cycle,event)
    box_w = 64
    gap = 16
    total_w = len(states)*box_w + (len(states)-1)*gap
    start_x = px + (pw-total_w)/2
    by = py+91
    for i,s in enumerate(states):
        bx = start_x + i*(box_w+gap)
        col = {
            "pending":(28,44,35),
            "active":(245,158,11),
            "loss":RED,
            "win":GREEN2
        }[s]
        d.rounded_rectangle((bx,by,bx+box_w,by+46), radius=12, fill=col, outline=(68,90,76), width=1)
        ff = font(18,True)
        label = str(i+1)
        bb=d.textbbox((0,0),label,font=ff)
        d.text((bx+(box_w-(bb[2]-bb[0]))/2,by+11),label,font=ff,fill=WHITE)

    # Live metrics from event snapshot.
    pnl = event.get("pnl",0)
    stake = event.get("stake",0)
    count = int(event.get("tradeCount") or 0)
    xs=[42,382,722]
    labels=["CYCLE P/L","CURRENT STAKE","TRADES"]
    values=[money(pnl),plain_money(stake),str(count)]
    colors=[GREEN2 if float(pnl or 0)>=0 else RED,WHITE,WHITE]
    sizes=[48,46,62]
    for i in range(3):
        cx=xs[i]
        d.rounded_rectangle((cx,METRIC_TOP,cx+296,METRIC_BOTTOM),radius=28,fill=(10,24,18),outline=LINE,width=2)
        d.text((cx+22,METRIC_TOP+22),labels[i],font=font(19,True),fill=MUTED)
        d.text((cx+22,METRIC_TOP+86),values[i],font=font(sizes[i],True),fill=colors[i])

    # Helpful current digit strip.
    current_digit = event.get("currentDigit")
    current_tick = str(event.get("currentTick") or "")
    d.rounded_rectangle((42,1524,1038,1628), radius=26, fill=(8,19,14), outline=LINE, width=2)
    d.text((70,1548),"LIVE MARKET",font=font(18,True),fill=MUTED)
    market_text = f"Current digit: {current_digit if current_digit is not None else '-'}"
    if current_tick:
        market_text += f"  ·  Tick {current_tick}"
    d.text((70,1581),market_text,font=fit_font(d,market_text,930,start=27,minimum=17,bold=True),fill=WHITE)

    d.text((46,1680),"Full captured browser viewport · no interface crop",font=font(18),fill=MUTED)
    right(d,website.replace("https://",""),1034,1678,font(19,True),GREEN2)
    center(d,"Past results do not guarantee future performance.",1740,font(17),MUTED)

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


def build_live_video(ffmpeg, raw, layout, duration, out):
    # Inner browser viewport: preserve complete source, no crop.
    ix=SCREEN["x"]+18
    iy=SCREEN["y"]+78
    iw=SCREEN["w"]-36
    ih=SCREEN["h"]-96

    ratio=f"{iw}/{ih}"
    filter_complex=(
        f"[0:v]scale='if(gt(a,{ratio}),{iw},-2)':'if(gt(a,{ratio}),-2,{ih})',setsar=1,"
        f"pad={iw}:{ih}:(ow-iw)/2:(oh-ih)/2:color=0x05090d[screen];"
        f"[1:v][screen]overlay={ix}:{iy}:shortest=1,fps=30,format=yuv420p[outv]"
    )

    run_ffmpeg([
        ffmpeg,"-y","-i",str(raw),"-i",str(layout),
        "-filter_complex",filter_complex,
        "-map","[outv]",*X264,"-movflags","+faststart","-an",str(out)
    ],"full-screen-guided")


def build_focus_replay(ffmpeg, raw, cycle, account_type, website, duration, td, out):
    # Gentle replay; still preserves the full captured viewport.
    event=(cycle.get("captureEvents") or [default_event(cycle)])[-1]
    frame=td/"focus_frame.png"
    event={**event,"title":"FOCUS REPLAY","subtitle":"Rewatching the final trading moment"}
    build_live_frame(cycle,account_type,website,event,frame)

    replay_duration=min(1.6,max(0.8,duration))
    start=max(0.0,duration-replay_duration)

    ix=SCREEN["x"]+18
    iy=SCREEN["y"]+78
    iw=SCREEN["w"]-36
    ih=SCREEN["h"]-96
    ratio=f"{iw}/{ih}"
    filter_complex=(
        f"[0:v]scale='if(gt(a,{ratio}),{iw},-2)':'if(gt(a,{ratio}),-2,{ih})',setsar=1,"
        f"pad={iw}:{ih}:(ow-iw)/2:(oh-ih)/2:color=0x05090d[screen];"
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

    add_tone(0.12,0.12,440,0.07)
    add_tone(0.34,0.14,660,0.07)

    t=live_start+0.5
    while t<live_end-0.3:
        add_tone(t,0.035,1400,0.025)
        t+=0.9

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
        outro_png=td/"outro.png"
        build_intro(cycle,account_type,intro_png)
        build_outro(cycle,website,outro_png)

        intro=td/"intro.mp4"
        outro=td/"outro.mp4"
        image_clip(ffmpeg,intro_png,0.8,intro)
        image_clip(ffmpeg,outro_png,1.25,outro)

        layout,duration=build_layout_timeline(ffmpeg,cycle,account_type,website,raw_duration,td)
        live=td/"live.mp4"
        build_live_video(ffmpeg,raw,layout,duration,live)

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

        total=0.8+duration+focus_duration+1.25
        sound=td/"sound.wav"
        build_soundtrack(total,0.8,0.8+duration+focus_duration,
                         str(cycle.get("status") or "").upper()=="WIN",sound)

        if raw_has_audio:
            run_ffmpeg([
                ffmpeg,"-y","-i",str(silent),"-i",str(sound),"-i",str(raw),
                "-filter_complex",
                "[1:a]volume=0.20[sfx];"
                "[2:a]adelay=800|800,volume=1.0[bot];"
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


async def send_video(video: Path, caption: str, chat: str):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","")
    if not token or not chat:
        raise RuntimeError("Telegram is not configured")
    async with httpx.AsyncClient(timeout=300) as client:
        with video.open("rb") as fh:
            r=await client.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={
                    "chat_id":chat,
                    "caption":caption[:950],
                    "parse_mode":"HTML",
                    "supports_streaming":"true"
                },
                files={"video":(video.name,fh,"video/mp4")}
            )
        data=r.json()
        if not r.is_success or not data.get("ok"):
            raise RuntimeError(data.get("description") or "sendVideo failed")
        return data["result"]


@app.get("/")
def root():
    return {"ok":True,"version":"premium-guided-v5.0"}


@app.get("/health")
def health():
    return {
        "ok":True,
        "version":"premium-guided-v5.0",
        "cors":True,
        "telegramConfigured":bool(
            os.environ.get("TELEGRAM_BOT_TOKEN") and
            os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        )
    }


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

    admin=os.environ.get("TELEGRAM_ADMIN_CHAT_ID","")
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
                if total>150*1024*1024:
                    raise HTTPException(status_code=413,detail="Live capture is too large")
                out.write(chunk)

        c["marketName"]=c.get("marketName") or c.get("symbol") or "Digit Match"

        final=td/"digitmatchstar-premium-guided.mp4"
        compose_guided(raw,c,str(claims.get("accountType") or "DEMO"),website,final)

        msg=await send_video(
            final,
            "🎥 <b>DIGITMATCHSTAR PREMIUM GUIDED VIDEO</b>\n"
            "Full browser capture with guided bot-status timeline, trade progress and real tab audio.\n"
            "Review before posting.",
            admin
        )

    return {
        "ok":True,
        "privateTelegramMessageId":msg.get("message_id"),
        "format":"1080x1920-h264-aac",
        "source":"full-browser-capture",
        "version":"premium-guided-v5.0",
        "features":[
            "full-screen-preserved",
            "guided-status-timeline",
            "trade-progress",
            "live-metrics",
            "focus-replay",
            "bot-tab-audio",
            "telegram-delivery"
        ]
    }
