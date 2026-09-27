import os, io, json, wave, math, random, hmac, hashlib, base64, tempfile, subprocess, re
from pathlib import Path
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

app = FastAPI(title="DigitMatchStar Ultra Premium Live Compositor v4.4")

# Browser uploads come directly from DigitMatchStar to Render.
# CORS lives in app.py itself so it works with BOTH `uvicorn app:app`
# and `uvicorn main:app`.
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
BG=(5,13,9); WHITE=(247,250,248); MUTED=(150,170,159)
GREEN=(34,197,94); GREEN2=(74,222,128); RED=(239,68,68); GOLD=(215,181,109); CYAN=(34,211,238)
LINE=(43,73,57); PANEL=(11,26,19); PANEL2=(8,19,14)

VIDEO_WELL = dict(x=90, y=530, w=900, h=860)

def font(size: int, bold: bool=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()

FONT_REG_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def center(d, t, y, ff, fill=WHITE):
    b = d.textbbox((0,0), str(t), font=ff)
    d.text(((W-(b[2]-b[0]))//2, y), str(t), font=ff, fill=fill)

def right(d, t, x, y, ff, fill=WHITE):
    b = d.textbbox((0,0), str(t), font=ff)
    d.text((x-(b[2]-b[0]), y), str(t), font=ff, fill=fill)

def money(v):
    n=float(v or 0)
    return f"{'+' if n>=0 else '-'}${abs(n):.2f}"

def probe_media(ffmpeg_path: str, media_path: Path):
    """Return (duration_seconds, has_audio) using ffmpeg itself."""
    try:
        r = subprocess.run(
            [str(ffmpeg_path), "-hide_banner", "-i", str(media_path)],
            capture_output=True, text=True
        )
        text = (r.stderr or "") + "\n" + (r.stdout or "")

        duration = 10.0
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if m:
            hh, mm, ss = m.groups()
            duration = max(
                0.2,
                int(hh) * 3600 + int(mm) * 60 + float(ss)
            )

        has_audio = bool(re.search(r"Stream #.*Audio:", text))
        return duration, has_audio
    except Exception:
        return 10.0, False

def sanitize_text(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'").replace(",", r"\,")

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
        if int(payload.get("exp",0)) < now:
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid or expired live-capture ticket")

def safe_json(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cycle JSON")

def hook_variant(cycle: dict):
    cid = str(cycle.get("id") or "")
    seed = int(hashlib.sha1(cid.encode()).hexdigest()[:8], 16) if cid else random.randint(1,9999)
    random.seed(seed)
    win = str(cycle.get("status") or "").upper() == "WIN"
    n = len(cycle.get("trades") or [])
    hit = cycle.get("winningTradeNumber") or n
    options_win = [
        ("REAL BOT. REAL CYCLE.", "Watch the actual screen go from entry to match."),
        ("WATCH THE BOT HIT THE DIGIT.", f"It matched on trade {hit}."),
        ("THIS IS LIVE EVIDENCE.", "The central video is the real DigitMatchStar tab."),
        ("CAN THE BOT MATCH BEFORE THE LIMIT?", f"Here is the actual result: MATCH on trade {hit}.")
    ]
    options_stop = [
        ("REAL BOT. REAL CYCLE.", "This one reached the stop limit."),
        ("THIS IS LIVE EVIDENCE.", "The central video is the real DigitMatchStar tab."),
        ("CAN THE BOT MATCH BEFORE THE LIMIT?", "Watch how the cycle ended at the risk limit."),
        ("ACTUAL SCREEN RECORDING.", "This result was recorded from the live tab.")
    ]
    return random.choice(options_win if win else options_stop)

def build_frame(cycle: dict, account_type: str, website: str, out: Path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.ellipse((-260,-200,500,520), fill=(7,48,28))
    d.ellipse((750,10,1320,620), fill=(47,38,12))
    d.rounded_rectangle((42,42,1038,1878), radius=54, outline=(25,48,35), width=2)

    d.text((70,70), "DIGITMATCHSTAR", font=font(42,True), fill=GREEN2)
    d.text((70,130), "ULTRA-PREMIUM LIVE EVIDENCE", font=font(21,True), fill=CYAN)

    acct="REAL ACCOUNT" if account_type=="REAL" else "DEMO ACCOUNT"
    d.rounded_rectangle((70,198,1010,316), radius=28, fill=PANEL2, outline=LINE, width=2)
    d.text((108,236), acct, font=font(23,True), fill=GOLD if account_type=="REAL" else GREEN2)
    market = str(cycle.get("marketName") or cycle.get("symbol") or "Digit Match")
    right(d, market, 972, 234, font(24,True), WHITE)

    d.rounded_rectangle((70,342,1010,470), radius=28, fill=PANEL, outline=LINE, width=2)
    d.text((108,380), "TARGET DIGIT", font=font(22,True), fill=MUTED)
    d.text((334,360), str(cycle.get("digit","-")), font=font(60,True), fill=GREEN2)

    win = str(cycle.get("status") or "").upper() == "WIN"
    n = len(cycle.get("trades") or [])
    result = f"MATCHED · TRADE {cycle.get('winningTradeNumber') or n}" if win else f"STOPPED · {n} TRADES"
    right(d, result, 970, 378, font(28,True), GREEN2 if win else RED)

    d.rounded_rectangle((VIDEO_WELL["x"], VIDEO_WELL["y"], VIDEO_WELL["x"]+VIDEO_WELL["w"], VIDEO_WELL["y"]+VIDEO_WELL["h"]),
                        radius=34, fill=(2,6,4), outline=(56,92,71), width=3)
    d.text((VIDEO_WELL["x"]+20, VIDEO_WELL["y"]+20), "ACTUAL BOT SCREEN", font=font(18,True), fill=MUTED)

    # lower panel
    d.rounded_rectangle((70,1442,1010,1688), radius=32, fill=PANEL, outline=LINE, width=2)
    d.text((108,1482), "CYCLE P/L", font=font(24), fill=MUTED)
    pnl = float(cycle.get("netPnL") or 0)
    d.text((108,1524), money(pnl), font=font(58,True), fill=GREEN2 if pnl>=0 else RED)
    d.text((595,1482), "TOTAL STAKE", font=font(24), fill=MUTED)
    d.text((595,1526), f"${float(cycle.get('totalInvestment') or 0):.2f}", font=font(36,True), fill=WHITE)

    d.line((70,1732,1010,1732), fill=LINE, width=2)
    d.text((70,1768), "Recorded live from the DigitMatchStar tab", font=font(18,True), fill=MUTED)
    right(d, website.replace("https://",""), 1010, 1768, font(18,True), GREEN2)
    center(d, "Past results do not guarantee future performance.", 1830, font(17), MUTED)
    im.save(out)

def build_intro(cycle: dict, account_type: str, out: Path):
    headline, sub = hook_variant(cycle)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((-300,-300,560,560), fill=(8,48,28))
    d.ellipse((730,0,1350,650), fill=(47,38,12))
    center(d, "DIGITMATCHSTAR", 330, font(66,True), GREEN2)
    center(d, headline, 440, font(44,True), WHITE)
    center(d, sub, 525, font(25), MUTED)
    d.rounded_rectangle((220,730,860,900), radius=84, fill=(11,33,22), outline=(44,116,74), width=3)
    center(d, "● LIVE SCREEN RECORDING", 788, font(30,True), CYAN)
    center(d, str(cycle.get("marketName") or cycle.get("symbol") or "Digit Match"), 1035, font(30,True), WHITE)
    center(d, f"Target digit {cycle.get('digit','-')}", 1092, font(27), GREEN2)
    center(d, "The actual trading screen appears in the next scene.", 1370, font(24,True), WHITE)
    center(d, "Trading involves risk.", 1450, font(20), MUTED)
    im.save(out)

def build_outro(cycle: dict, website: str, out: Path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.ellipse((-260,-220,520,550), fill=(9,50,29))
    status = str(cycle.get("status") or "").upper()
    win = status == "WIN"
    n = len(cycle.get("trades") or [])
    center(d, "CYCLE COMPLETE", 320, font(34,True), MUTED)
    center(d, "MATCHED" if win else "STOPPED", 435, font(90,True), GREEN2 if win else RED)
    if win:
        center(d, f"TRADE {cycle.get('winningTradeNumber') or n}", 555, font(48,True), WHITE)
    center(d, money(cycle.get("netPnL",0)), 735, font(104,True), GREEN2 if float(cycle.get("netPnL",0) or 0) >= 0 else RED)
    center(d, "Actual screen recording placed in a premium vertical format", 980, font(27,True), WHITE)
    center(d, "Built for TikTok, Reels and Telegram", 1040, font(25), MUTED)
    center(d, website.replace("https://",""), 1225, font(38,True), GREEN2)
    center(d, "Past results do not guarantee future performance.", 1510, font(20), MUTED)
    im.save(out)

def trade_times(cycle: dict, raw_duration: float):
    start_ms = float(cycle.get("startedAt") or 0) or None
    trades = cycle.get("trades") or []
    rows = []
    for i, t in enumerate(trades[:12]):
        if start_ms and t.get("purchasedAt"):
            ts = max(0.0, (float(t["purchasedAt"]) - start_ms) / 1000.0)
        else:
            ts = min(raw_duration * 0.8, i * max(0.5, raw_duration / max(1, len(trades)+1)))
        if start_ms and t.get("settledAt"):
            te = max(ts + 0.2, (float(t["settledAt"]) - start_ms) / 1000.0)
        else:
            te = min(raw_duration, ts + 0.8)
        rows.append({
            "idx": i+1,
            "start": round(max(0.0, min(ts, raw_duration)), 3),
            "end": round(max(0.0, min(te, raw_duration)), 3),
            "result": str(t.get("result") or "").upper() or "MISS"
        })
    return rows

def build_overlay_filter(cycle: dict, raw_duration: float):
    pieces = []
    x0 = 120
    gap = 68
    y = 1328
    bar_w = 54
    fontfile = FONT_BOLD_PATH if Path(FONT_BOLD_PATH).exists() else FONT_REG_PATH

    rows = trade_times(cycle, raw_duration)
    for i, row in enumerate(rows):
        x = x0 + i * gap
        start = row["start"]
        end = max(row["start"] + 0.12, row["end"])
        final_color = "0x22c55e@0.92" if row["result"] == "WIN" else "0xef4444@0.92"

        # base shadow visible from t=0
        pieces.append(f"drawbox=x={x}:y={y}:w={bar_w}:h=28:color=white@0.06:t=fill")
        # active interval
        pieces.append(f"drawbox=x={x}:y={y}:w={bar_w}:h=28:color=0xf59e0b@0.95:t=fill:enable='between(t,{start},{end})'")
        # final state from end onwards
        pieces.append(f"drawbox=x={x}:y={y}:w={bar_w}:h=28:color={final_color}:t=fill:enable='gte(t,{end})'")
        # label
        pieces.append(
            f"drawtext=fontfile='{fontfile}':text='{row['idx']}':x={x+18}:y={y+4}:fontsize=16:fontcolor=white:enable='gte(t,{max(0.0, start-0.05)})'"
        )

    pieces.append(
        f"drawtext=fontfile='{fontfile}':text='LIVE CYCLE':x=140:y=582:fontsize=26:fontcolor=white@0.95"
    )
    pieces.append(
        f"drawtext=fontfile='{fontfile}':text='TRADE PROGRESS':x=770:y=1300:fontsize=20:fontcolor=white@0.85"
    )
    return ",".join(pieces)

def render_live_sections(raw_video: Path, frame_png: Path, cycle: dict, ffmpeg: str, td: Path):
    raw_duration, raw_has_audio = probe_media(ffmpeg, raw_video)

    overlay_filter = build_overlay_filter(cycle, raw_duration)
    full_live = td / "live_full.mp4"
    cmd_full = [
        ffmpeg, "-y", "-i", str(raw_video), "-loop", "1", "-i", str(frame_png),
        "-filter_complex",
        (
            f"[0:v]scale={VIDEO_WELL['w']}:{VIDEO_WELL['h']}:force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_WELL['w']}:{VIDEO_WELL['h']}:(ow-iw)/2:(oh-ih)/2:color=black[screen];"
            f"[1:v][screen]overlay={VIDEO_WELL['x']}:{VIDEO_WELL['y']}:shortest=1[base];"
            f"[base]{overlay_filter},fps=30,format=yuv420p[outv]"
        ),
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
        str(full_live)
    ]
    subprocess.run(cmd_full, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Focus zoom section from late in the clip.
    focus_live = td / "live_focus.mp4"
    zoom_start = max(0.0, raw_duration - 1.4)
    zoom_duration = min(1.4, raw_duration)
    cmd_focus = [
        ffmpeg, "-y", "-ss", str(zoom_start), "-t", str(zoom_duration),
        "-i", str(raw_video), "-loop", "1", "-i", str(frame_png),
        "-filter_complex",
        (
            f"[0:v]scale=1180:1130:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WELL['w']}:{VIDEO_WELL['h']}:(iw-{VIDEO_WELL['w']})/2:(ih-{VIDEO_WELL['h']})/2[screen];"
            f"[1:v][screen]overlay={VIDEO_WELL['x']}:{VIDEO_WELL['y']}:shortest=1[base];"
            f"[base]drawtext=fontfile='{FONT_BOLD_PATH if Path(FONT_BOLD_PATH).exists() else FONT_REG_PATH}':"
            f"text='FOCUS REPLAY':x=126:y=580:fontsize=28:fontcolor={ '0x86efac' },"
            f"drawtext=fontfile='{FONT_BOLD_PATH if Path(FONT_BOLD_PATH).exists() else FONT_REG_PATH}':"
            f"text='Watch the final moment again':x=126:y=615:fontsize=18:fontcolor=white@0.85,"
            f"fps=30,format=yuv420p[outv]"
        ),
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
        str(focus_live)
    ]
    subprocess.run(cmd_focus, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return full_live, focus_live, raw_duration, zoom_duration, raw_has_audio

def image_clip(ffmpeg: str, image_path: Path, duration: float, out: Path):
    subprocess.run([
        ffmpeg, "-y", "-loop", "1", "-t", str(duration), "-i", str(image_path),
        "-vf", f"fps=30,format=yuv420p,fade=t=in:st=0:d=0.15,fade=t=out:st={max(.1,duration-.18)}:d=0.18",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def build_soundtrack(total_duration: float, live_start: float, live_end: float, is_win: bool, out_wav: Path):
    sr = 44100
    samples = int(total_duration * sr)
    data = [0.0] * samples

    def add_tone(start, dur, freq, amp=0.18):
        a = int(start * sr)
        b = min(samples, int((start + dur) * sr))
        for i in range(a, b):
            t = (i - a) / sr
            # Soft attack/release envelope
            env = min(1.0, t / 0.03) * min(1.0, max(0.0, (dur - t) / 0.05))
            data[i] += amp * env * math.sin(2 * math.pi * freq * t)

    def add_tick(start, dur=0.05, freq=1500, amp=0.08):
        add_tone(start, dur, freq, amp)

    # intro pulses
    add_tone(0.18, 0.16, 440, 0.11)
    add_tone(0.43, 0.18, 660, 0.10)
    add_tone(0.68, 0.22, 880, 0.10)

    # subtle ticks during live section every ~0.7 s
    t = live_start + 0.35
    while t < live_end - 0.35:
        add_tick(t)
        t += 0.7

    # final result sting
    if is_win:
        add_tone(max(0.0, live_end - 0.05), 0.12, 740, 0.13)
        add_tone(max(0.0, live_end + 0.10), 0.14, 988, 0.13)
        add_tone(max(0.0, live_end + 0.26), 0.18, 1244, 0.13)
    else:
        add_tone(max(0.0, live_end + 0.05), 0.22, 220, 0.11)
        add_tone(max(0.0, live_end + 0.30), 0.26, 196, 0.11)

    # gentle outro tone
    add_tone(max(0.0, total_duration - 0.55), 0.28, 392 if is_win else 262, 0.06)

    # clamp and write wav
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for x in data:
            v = max(-1.0, min(1.0, x))
            frames += int(v * 32767).to_bytes(2, byteorder="little", signed=True)
        wf.writeframes(frames)

def compose_ultra(raw_video: Path, cycle: dict, account_type: str, website: str, out_video: Path):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        frame = td / "frame.png"
        intro = td / "intro.png"
        outro = td / "outro.png"
        build_frame(cycle, account_type, website, frame)
        build_intro(cycle, account_type, intro)
        build_outro(cycle, website, outro)

        intro_v = td / "intro.mp4"
        outro_v = td / "outro.mp4"
        image_clip(ffmpeg, intro, 1.10, intro_v)
        image_clip(ffmpeg, outro, 1.65, outro_v)

        full_live, focus_live, raw_duration, focus_duration, raw_has_audio = render_live_sections(raw_video, frame, cycle, ffmpeg, td)

        concat_list = td / "concat.txt"
        concat_list.write_text(
            f"file '{intro_v.as_posix()}'\n"
            f"file '{full_live.as_posix()}'\n"
            f"file '{focus_live.as_posix()}'\n"
            f"file '{outro_v.as_posix()}'\n"
        )
        silent_video = td / "silent.mp4"
        subprocess.run([
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an",
            str(silent_video)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        total_duration = 1.10 + raw_duration + focus_duration + 1.65
        live_start = 1.10
        live_end = 1.10 + raw_duration + focus_duration
        sound = td / "sound.wav"
        build_soundtrack(total_duration, live_start, live_end, str(cycle.get("status") or "").upper() == "WIN", sound)

        if raw_has_audio:
            # Preserve the actual DigitMatchStar tab audio (ticks, win sounds, etc.)
            # underneath the premium sound design. The live capture begins after
            # the 1.10s branded intro.
            subprocess.run([
                ffmpeg, "-y",
                "-i", str(silent_video),
                "-i", str(sound),
                "-i", str(raw_video),
                "-filter_complex",
                (
                    "[1:a]volume=0.22[sfx];"
                    "[2:a]adelay=1100|1100,volume=1.0[bot];"
                    "[sfx][bot]amix=inputs=2:duration=longest:dropout_transition=1[aout]"
                ),
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "160k",
                "-shortest",
                "-movflags", "+faststart",
                str(out_video)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run([
                ffmpeg, "-y", "-i", str(silent_video), "-i", str(sound),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                "-movflags", "+faststart", str(out_video)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

async def send_video(video: Path, caption: str, chat: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat:
        raise RuntimeError("Telegram is not configured")
    async with httpx.AsyncClient(timeout=240) as client:
        with video.open("rb") as fh:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={
                    "chat_id": chat,
                    "caption": caption[:950],
                    "parse_mode": "HTML",
                    "supports_streaming": "true"
                },
                files={"video": (video.name, fh, "video/mp4")}
            )
        d = r.json()
        if not r.is_success or not d.get("ok"):
            raise RuntimeError(d.get("description") or "sendVideo failed")
        return d["result"]

@app.get("/health")
def health():
    return {
        "ok": True,
        "version": "ultra-premium-live-v4.4",
        "cors": True,
        "telegramConfigured": bool(
            os.environ.get("TELEGRAM_BOT_TOKEN") and
            os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
        )
    }

@app.post("/compose-live")
async def compose_live_endpoint(
    video: UploadFile = File(...),
    ticket: str = Form(...),
    cycle: str = Form(...),
    website: str = Form("https://www.digitmatchstar.com")
):
    claims = decode_ticket(ticket)
    c = safe_json(cycle)

    if str(c.get("id") or "") != str(claims.get("cycleId") or ""):
        raise HTTPException(status_code=400, detail="Cycle id does not match upload ticket")

    admin = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin:
        raise HTTPException(status_code=500, detail="TELEGRAM_ADMIN_CHAT_ID is missing")

    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        raw = td / "capture.webm"
        total = 0
        with raw.open("wb") as out:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 120 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Live capture is too large")
                out.write(chunk)

        # normalize helpful fields
        c["marketName"] = c.get("marketName") or c.get("symbol") or "Digit Match"

        final = td / "digitmatchstar-ultra-premium-live.mp4"
        compose_ultra(raw, c, str(claims.get("accountType") or "DEMO"), website, final)

        msg = await send_video(
            final,
            "🔥 <b>DIGITMATCHSTAR PREMIUM LIVE VIDEO</b>\n"
            "Actual DigitMatchStar screen capture inside a premium vertical TikTok/Telegram format.\n"
            "Includes hook, progress rail, focus replay and audio sting.\n"
            "Review before posting.",
            admin
        )

    return {
        "ok": True,
        "privateTelegramMessageId": msg.get("message_id"),
        "format": "1080x1920-h264-aac",
        "source": "actual-screen-capture",
        "features": ["hook-variant", "trade-progress-rail", "focus-replay", "bot-tab-audio", "premium-sound-design"]
    }


# === Render-portable compositor overrides v4.4 ===
# Avoid FFmpeg drawtext because the imageio static FFmpeg build does not include it.

def _run_ffmpeg(cmd, stage: str):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or '')[-6000:]
        print(f'[FFMPEG:{stage}] failed rc={r.returncode}\\n{tail}', flush=True)
        raise RuntimeError(f'FFmpeg {stage} failed: {tail[-1200:]}')
    return r

_build_frame_v43 = build_frame

def build_frame(cycle: dict, account_type: str, website: str, out: Path):
    _build_frame_v43(cycle, account_type, website, out)


def build_hud(cycle: dict, out: Path, focus: bool=False):
    im = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(im)
    if focus:
        d.text((126,580), 'FOCUS REPLAY', font=font(28,True), fill=(134,239,172,255))
        d.text((126,615), 'Watch the final moment again', font=font(18,True), fill=(255,255,255,220))
    else:
        d.text((140,582), 'LIVE CYCLE', font=font(26,True), fill=(255,255,255,242))
        d.text((770,1300), 'TRADE PROGRESS', font=font(20,True), fill=(255,255,255,215))
        trades = cycle.get('trades') or []
        x0, gap, y = 120, 68, 1360
        for i, _ in enumerate(trades[:12]):
            label = str(i+1)
            ff = font(15,True)
            b = d.textbbox((0,0), label, font=ff)
            tw = b[2]-b[0]
            d.text((x0+i*gap + (54-tw)//2, y), label, font=ff, fill=(255,255,255,220))
    im.save(out)


def build_overlay_filter(cycle: dict, raw_duration: float):
    pieces = []
    x0, gap, y, bar_w = 120, 68, 1328, 54
    rows = trade_times(cycle, raw_duration)
    for i, row in enumerate(rows):
        x = x0 + i * gap
        start = row['start']
        end = max(row['start'] + 0.12, row['end'])
        final_color = '0x22c55e@0.92' if row['result'] == 'WIN' else '0xef4444@0.92'
        pieces.append(f'drawbox=x={x}:y={y}:w={bar_w}:h=28:color=white@0.06:t=fill')
        pieces.append(f"drawbox=x={x}:y={y}:w={bar_w}:h=28:color=0xf59e0b@0.95:t=fill:enable='between(t,{start},{end})'")
        pieces.append(f"drawbox=x={x}:y={y}:w={bar_w}:h=28:color={final_color}:t=fill:enable='gte(t,{end})'")
    return ','.join(pieces) if pieces else 'null'


def render_live_sections(raw_video: Path, frame_png: Path, cycle: dict, ffmpeg: str, td: Path):
    raw_duration, raw_has_audio = probe_media(ffmpeg, raw_video)
    hud = td / 'hud.png'
    focus_hud = td / 'focus_hud.png'
    build_hud(cycle, hud, False)
    build_hud(cycle, focus_hud, True)

    overlay_filter = build_overlay_filter(cycle, raw_duration)
    full_live = td / 'live_full.mp4'
    cmd_full = [
        ffmpeg, '-y', '-i', str(raw_video), '-loop', '1', '-i', str(frame_png), '-loop', '1', '-i', str(hud),
        '-filter_complex',
        (
            f"[0:v]scale={VIDEO_WELL['w']}:{VIDEO_WELL['h']}:force_original_aspect_ratio=decrease,"
            f"pad={VIDEO_WELL['w']}:{VIDEO_WELL['h']}:(ow-iw)/2:(oh-ih)/2:color=black[screen];"
            f"[1:v][screen]overlay={VIDEO_WELL['x']}:{VIDEO_WELL['y']}:shortest=1[base];"
            f"[base]{overlay_filter}[progress];"
            f"[progress][2:v]overlay=0:0:shortest=1,fps=30,format=yuv420p[outv]"
        ),
        '-map', '[outv]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
        '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', str(full_live)
    ]
    _run_ffmpeg(cmd_full, 'live-full')

    focus_live = td / 'live_focus.mp4'
    zoom_start = max(0.0, raw_duration - 1.4)
    zoom_duration = min(1.4, raw_duration)
    cmd_focus = [
        ffmpeg, '-y', '-ss', str(zoom_start), '-t', str(zoom_duration), '-i', str(raw_video),
        '-loop', '1', '-i', str(frame_png), '-loop', '1', '-i', str(focus_hud),
        '-filter_complex',
        (
            f"[0:v]scale=1180:1130:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WELL['w']}:{VIDEO_WELL['h']}:(iw-{VIDEO_WELL['w']})/2:(ih-{VIDEO_WELL['h']})/2[screen];"
            f"[1:v][screen]overlay={VIDEO_WELL['x']}:{VIDEO_WELL['y']}:shortest=1[base];"
            f"[base][2:v]overlay=0:0:shortest=1,fps=30,format=yuv420p[outv]"
        ),
        '-map', '[outv]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
        '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', str(focus_live)
    ]
    _run_ffmpeg(cmd_focus, 'focus-replay')
    return full_live, focus_live, raw_duration, zoom_duration, raw_has_audio


def image_clip(ffmpeg: str, image_path: Path, duration: float, out: Path):
    fade_out = max(0.10, duration - 0.18)
    cmd = [
        ffmpeg, '-y', '-loop', '1', '-t', str(duration), '-i', str(image_path),
        '-vf', f'fps=30,format=yuv420p,fade=t=in:st=0:d=0.15,fade=t=out:st={fade_out}:d=0.18',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-profile:v', 'high',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', str(out)
    ]
    _run_ffmpeg(cmd, 'image-clip')
