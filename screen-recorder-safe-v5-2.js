/*
 * DigitMatchStar Premium Recorder v7.0
 * Browser-only capture utility.
 * - Compatible with secure OAuth/server execution (no raw Deriv token required)
 * - Explicit browser screen-share permission is always required
 * - Does not patch, place, stop, or alter trades
 * - Records the current tab/screen and a lightweight event timeline
 */
(() => {
  'use strict';

  if (window.__DMS_PREMIUM_RECORDER_V7__) return;
  window.__DMS_PREMIUM_RECORDER_V7__ = true;

  const VERSION = '7.0-server-oauth-compatible';
  const state = {
    stream: null,
    recorder: null,
    chunks: [],
    startedAt: 0,
    panel: null,
    timer: null,
    events: [],
    lastFingerprint: '',
    saving: false,
  };

  const $ = id => document.getElementById(id);
  const txt = id => String($(id)?.textContent || '').trim();

  function platformAuthenticated() {
    const jwt =
      sessionStorage.getItem('dms_platform_jwt') ||
      localStorage.getItem('dms_platform_jwt') ||
      '';
    const flag =
      sessionStorage.getItem('bot_authenticated') === 'true' ||
      localStorage.getItem('bot_authenticated') === 'true';
    return !!jwt && flag;
  }

  function safeFileStamp() {
    return new Date().toISOString().replace(/[:.]/g, '-');
  }

  function numberFromText(v) {
    const n = Number(String(v ?? '').replace(/[^0-9+.-]/g, ''));
    return Number.isFinite(n) ? n : null;
  }

  function snapshot() {
    const s = window.SERVER_EXECUTION?.state || {};
    return {
      atMs: state.startedAt ? Date.now() - state.startedAt : 0,
      phase: String(s.phase || ''),
      accountMode: String(s.account_mode || ''),
      symbol: String(s.symbol || document.getElementById('symbolSelect')?.value || ''),
      candidateDigit: Number.isInteger(Number(s.candidate_digit))
        ? Number(s.candidate_digit)
        : null,
      currentTick: txt('metricLiveTick'),
      currentDigit: numberFromText(txt('metricLastDigit')),
      trade: Number(s.current_trade ?? numberFromText(txt('metricTradeCount')) ?? 0),
      maxTrades: Number(s.max_trades || 0),
      stake: Number(s.current_stake ?? numberFromText(txt('metricCurrentStake')) ?? 0),
      pnl: Number(s.pnl ?? numberFromText(txt('metricTotalProfit')) ?? 0),
      balance: Number(s.account_balance ?? numberFromText(txt('metricAccountBalance')) ?? 0),
      contractId: s.open_contract_id || null,
      result: txt('metricTradeResult'),
      status: txt('metricPreviousResult'),
      action: txt('metricNextAction'),
    };
  }

  function captureTimelineEvent(force = false) {
    if (!state.startedAt) return;
    const row = snapshot();
    const fp = JSON.stringify([
      row.phase, row.candidateDigit, row.currentTick, row.currentDigit,
      row.trade, row.stake, row.pnl, row.contractId,
      row.result, row.status, row.action
    ]);
    if (!force && fp === state.lastFingerprint) return;
    state.lastFingerprint = fp;
    state.events.push(row);
    if (state.events.length > 500) state.events.shift();
  }

  function setStatus(message, tone = 'muted') {
    const el = $('dms70-rec-status');
    if (!el) return;
    el.textContent = message;
    const colors = {
      muted: '#94a3b8',
      good: '#86efac',
      warn: '#fde68a',
      bad: '#fca5a5',
      live: '#f87171',
    };
    el.style.color = colors[tone] || colors.muted;
  }

  function mimeType() {
    const candidates = [
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm',
    ];
    return candidates.find(t => window.MediaRecorder?.isTypeSupported?.(t)) || '';
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  function downloadTimeline() {
    const payload = {
      product: 'DigitMatchStar',
      recorderVersion: VERSION,
      generatedAt: new Date().toISOString(),
      events: state.events,
    };
    downloadBlob(
      new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }),
      `digitmatchstar-recording-${safeFileStamp()}.json`
    );
  }

  async function stopAndSave(reason = 'manual') {
    if (state.saving) return;
    state.saving = true;

    try {
      captureTimelineEvent(true);
      if (state.timer) {
        clearInterval(state.timer);
        state.timer = null;
      }

      const rec = state.recorder;
      if (rec && rec.state !== 'inactive') {
        await new Promise(resolve => {
          rec.addEventListener('stop', resolve, { once: true });
          try { rec.stop(); } catch (_) { resolve(); }
        });
      }

      const blob = new Blob(state.chunks, {
        type: rec?.mimeType || 'video/webm'
      });

      if (blob.size > 0) {
        downloadBlob(
          blob,
          `digitmatchstar-${safeFileStamp()}.webm`
        );
        downloadTimeline();
        setStatus(`Saved ${(blob.size / 1024 / 1024).toFixed(1)} MB video + timeline`, 'good');
      } else {
        setStatus('Recording stopped, but no video data was captured.', 'warn');
      }
    } finally {
      try {
        state.stream?.getTracks?.().forEach(track => track.stop());
      } catch (_) {}
      state.stream = null;
      state.recorder = null;
      state.chunks = [];
      state.startedAt = 0;
      state.lastFingerprint = '';
      state.saving = false;

      const start = $('dms70-rec-start');
      const stop = $('dms70-rec-stop');
      if (start) start.disabled = false;
      if (stop) stop.disabled = true;
      const badge = $('dms70-rec-badge');
      if (badge) {
        badge.textContent = 'READY';
        badge.style.color = '#86efac';
      }
    }
  }

  async function startRecording() {
    if (!platformAuthenticated()) {
      setStatus('Authenticate with DigitMatchStar first.', 'warn');
      return;
    }
    if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) {
      setStatus('Screen recording is not supported in this browser.', 'bad');
      return;
    }

    try {
      setStatus('Choose this DigitMatchStar tab. Enable tab audio if you want sound.', 'warn');

      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          frameRate: { ideal: 30, max: 60 }
        },
        audio: true,
      });

      state.stream = stream;
      state.chunks = [];
      state.events = [];
      state.startedAt = Date.now();
      state.lastFingerprint = '';

      const mime = mimeType();
      const options = mime ? { mimeType: mime, videoBitsPerSecond: 6_000_000 } : {};
      const recorder = new MediaRecorder(stream, options);
      state.recorder = recorder;

      recorder.addEventListener('dataavailable', event => {
        if (event.data && event.data.size > 0) state.chunks.push(event.data);
      });

      recorder.addEventListener('error', event => {
        console.error('[DMS Recorder]', event.error || event);
        setStatus(`Recorder error: ${event.error?.message || 'unknown error'}`, 'bad');
      });

      const videoTrack = stream.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.addEventListener('ended', () => stopAndSave('share-ended'), { once: true });
      }

      recorder.start(1000);
      captureTimelineEvent(true);
      state.timer = setInterval(captureTimelineEvent, 350);

      $('dms70-rec-start').disabled = true;
      $('dms70-rec-stop').disabled = false;
      const badge = $('dms70-rec-badge');
      if (badge) {
        badge.textContent = '● RECORDING';
        badge.style.color = '#f87171';
      }
      setStatus('Recording live · STOP & SAVE when finished', 'live');
    } catch (error) {
      setStatus(
        error?.name === 'NotAllowedError'
          ? 'Recording permission was cancelled.'
          : `Could not start recorder: ${error?.message || error}`,
        'bad'
      );
    }
  }

  function makeDraggable(panel, handle) {
    let active = false, sx = 0, sy = 0, sl = 0, st = 0;
    handle.addEventListener('pointerdown', e => {
      if (e.target.closest('button')) return;
      active = true;
      const r = panel.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY; sl = r.left; st = r.top;
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
      panel.style.left = `${sl}px`;
      panel.style.top = `${st}px`;
      handle.setPointerCapture?.(e.pointerId);
    });
    handle.addEventListener('pointermove', e => {
      if (!active) return;
      const x = Math.max(0, Math.min(innerWidth - panel.offsetWidth, sl + e.clientX - sx));
      const y = Math.max(0, Math.min(innerHeight - panel.offsetHeight, st + e.clientY - sy));
      panel.style.left = `${x}px`;
      panel.style.top = `${y}px`;
    });
    const stop = () => { active = false; };
    handle.addEventListener('pointerup', stop);
    handle.addEventListener('pointercancel', stop);
  }

  function ensurePanel() {
    if ($('dms70-rec-panel')) return;

    const panel = document.createElement('div');
    panel.id = 'dms70-rec-panel';
    panel.style.cssText = [
      'position:fixed',
      'right:14px',
      'bottom:14px',
      'z-index:2147483646',
      'width:245px',
      'padding:11px',
      'border-radius:14px',
      'background:rgba(7,15,28,.97)',
      'border:1px solid rgba(56,189,248,.38)',
      'box-shadow:0 18px 45px rgba(0,0,0,.45)',
      'font-family:Inter,Arial,sans-serif',
      'color:#f8fafc',
    ].join(';');

    panel.innerHTML = `
      <div id="dms70-rec-drag" style="display:flex;align-items:center;gap:7px;cursor:move">
        <span>🎥</span>
        <span style="font-size:11px;font-weight:900;color:#7dd3fc;letter-spacing:.04em">
          PREMIUM RECORDER
        </span>
        <span id="dms70-rec-badge" style="margin-left:auto;font-size:9px;font-weight:900;color:#86efac">
          READY
        </span>
      </div>
      <div id="dms70-rec-status"
           style="font-size:10px;line-height:1.35;color:#94a3b8;margin:8px 0">
        Record the live bot screen + trade-status timeline.
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:7px">
        <button id="dms70-rec-start"
                style="border:0;border-radius:8px;padding:8px;background:#0284c7;color:#fff;font-size:10px;font-weight:900;cursor:pointer">
          ▶ RECORD
        </button>
        <button id="dms70-rec-stop" disabled
                style="border:0;border-radius:8px;padding:8px;background:#be123c;color:#fff;font-size:10px;font-weight:900;cursor:pointer;opacity:.95">
          ■ STOP & SAVE
        </button>
      </div>
      <div style="font-size:8.5px;line-height:1.3;color:#64748b;margin-top:7px">
        Browser permission is required. Selecting this tab gives the cleanest capture.
      </div>
    `;

    document.body.appendChild(panel);
    state.panel = panel;

    makeDraggable(panel, $('dms70-rec-drag'));
    $('dms70-rec-start')?.addEventListener('click', startRecording);
    $('dms70-rec-stop')?.addEventListener('click', () => stopAndSave('manual'));
  }

  function init() {
    ensurePanel();
    if (!platformAuthenticated()) {
      setStatus('Sign in to use the recorder.', 'warn');
    }
    console.log(`🎥 DigitMatchStar Premium Recorder ${VERSION} loaded`);
  }

  window.DMSRecorder = {
    version: VERSION,
    start: startRecording,
    stop: stopAndSave,
    snapshot,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
