# DigitMatchStar Ultra-Premium Live Video v4

This build goes beyond a simple result card.

It records the **actual DigitMatchStar trading screen** and turns it into an attention-focused vertical social video.

## What v4 adds

Compared with v3, this version adds:

- **Hook variants**  
  The intro line changes automatically between several high-attention hooks.

- **Trade-progress rail**  
  Small trade boxes appear and complete across the live segment.

- **Focus replay**  
  After the full live screen segment, the final moment is shown again in a tighter zoomed-in replay.

- **Synthetic sound design**  
  A light built-in audio sting is added so the video has motion and rhythm before TikTok music is added.

- **Real screen in the center**  
  The main visual proof remains the actual browser-tab recording.

## Final format

- 1080 × 1920
- H.264 video
- AAC audio
- 30 fps
- mobile-friendly fast-start MP4

## Flow

1. You enable tab capture once in Chrome/Edge.
2. DigitMatchStar starts a cycle.
3. The real tab is recorded automatically.
4. At cycle completion, the clip is uploaded with a short-lived signed ticket.
5. Render builds the ultra-premium social video.
6. The finished MP4 is sent privately to `TELEGRAM_ADMIN_CHAT_ID`.

## Included files

- `api/live-capture-ticket.js`
- `screen-recorder-v4.js`
- `media-worker/app.py`
- `media-worker/requirements.txt`
- `install_v4.py`

## Install

Copy the files to your repository in the same relative paths, then from repo root run:

```bash
python install_v4.py
```

This adds:

```html
<script src="/screen-recorder-v4.js"></script>
```

to the bot pages and removes earlier recorder tags.

## Environment

### Vercel
Required:
- `MEDIA_WORKER_URL`
- `MEDIA_WORKER_SECRET`
- `TELEGRAM_PUBLISH_ACCOUNT_IDS`

### Render
Required:
- `MEDIA_WORKER_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_CHAT_ID`

## Deploy order

1. Replace `media-worker/app.py`
2. Replace `media-worker/requirements.txt`
3. Redeploy Render
4. Confirm `/health` returns `ultra-premium-live-v4`
5. Add/replace `api/live-capture-ticket.js`
6. Add `screen-recorder-v4.js`
7. Run `python install_v4.py`
8. Deploy Vercel
9. Open DigitMatchStar in Chrome/Edge
10. Press **Enable live capture**
11. Choose the DigitMatchStar tab
12. Run a DEMO cycle first

## Important note

This system is designed to make the videos much more premium and attention-grabbing, but no honest system can guarantee a video will trend.

What it *can* do is give you:
- stronger visual credibility,
- better retention structure,
- better hook quality,
- better replay value,
- a more premium brand look than most simple template videos.

## Next possible step after v4

If you want, the next generation can add:
- auto-generated subtitles,
- multiple A/B hook exports from the same cycle,
- market-specific templates,
- AI voiceover,
- automatic hashtags/captions,
- separate templates for REAL vs DEMO results.
