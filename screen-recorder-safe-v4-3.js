/*
 * DigitMatchStar Premium Capture v4.3
 * READ-ONLY OBSERVER for bot-obfuscated.html.
 *
 * Important:
 * - Does NOT patch/replace trading functions.
 * - Starts recording immediately after screen-share permission so the
 *   settings/configuration period can be included.
 * - Requires tab audio so DigitMatchStar ticks/sounds can be captured.
 * - Hides this control completely from the recording.
 * - Small + draggable before capture.
 */
(() => {
  'use strict';

  const VERSION = '4.3-premium-observer';

  const state = {
    displayStream: null,
    recorder: null,
    chunks: [],
    captureStartedAt: null,
    activeCycleId: null,
    lastCompletedCycle: null,
    lastSeenCurrent: false,
    uploading: false,
    panel: null,
    observerTimer: null,
    lastBlobUrl: null
  };

  const clone = value => {
    try { return JSON.parse(JSON.stringify(value)); }
    catch (_) { return null; }
  };

  function cp() {
    const value = window.cyclePerformance;
    return value && typeof value === 'object' ? value : null;
  }

  function currentCycle() {
    const value = cp()?.current;
    return value && typeof value === 'object' ? value : null;
  }

  function cycleId(cycle) {
    return String(
      cycle?.id ??
      cycle?.cycleId ??
      cycle?.startedAt ??
      cycle?.startTime ??
      ''
    );
  }

  function allHistory() {
    const x = cp();
    if (!x) return [];
    const rows = [];

    if (x.historyBySymbol && typeof x.historyBySymbol === 'object') {
      for (const group of Object.values(x.historyBySymbol)) {
        if (Array.isArray(group)) rows.push(...group);
      }
    }

    if (Array.isArray(x.history)) rows.push(...x.history);
    if (Array.isArray(x.cycles)) rows.push(...x.cycles);
    if (Array.isArray(x.completed)) rows.push(...x.completed);

    return rows.filter(Boolean);
  }

  function findCompletedCycle(id) {
    if (!id) return null;
    const rows = allHistory();

    for (let i = rows.length - 1; i >= 0; i--) {
      if (cycleId(rows[i]) === String(id)) return clone(rows[i]);
    }

    const x = cp();
    for (const item of [
      x?.lastCompleted,
      x?.lastComplete,
      x?.lastCycle,
      x?.latest
    ]) {
      if (item && cycleId(item) === String(id)) return clone(item);
    }
    return null;
  }

  function getAccountId() {
    if (typeof window.getStoredDerivAccount === 'function') {
      try {
        const v = window.getStoredDerivAccount();
        if (v) return v;
      } catch (_) {}
    }

    const mode = String(
      localStorage.getItem('selectedAccountMode') || 'DEMO'
    ).toUpperCase();

    return (
      localStorage.getItem('active_account') ||
      localStorage.getItem('derivAccount') ||
      localStorage.getItem(mode === 'REAL' ? 'derivRealAccount' : 'derivDemoAccount') ||
      ''
    );
  }

  function getToken() {
    if (typeof window.getStoredDerivToken === 'function') {
      try {
        const v = window.getStoredDerivToken();
        if (v) return v;
      } catch (_) {}
    }

    return (
      localStorage.getItem('active_token') ||
      localStorage.getItem('derivToken') ||
      localStorage.getItem('deriv_token') ||
      localStorage.getItem('derivTokenDemo') ||
      localStorage.getItem('derivTokenReal') ||
      localStorage.getItem('authToken') ||
      ''
    );
  }

  function supportedMime() {
    return [
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm'
    ].find(type => window.MediaRecorder?.isTypeSupported?.(type)) || '';
  }

  function status(text, tone='muted') {
    const el = document.getElementById('dms43-status');
    if (!el) return;
    el.textContent = text;
    const colors = {
      muted:'#9ca3af',
      good:'#86efac',
      warn:'#fcd34d',
      bad:'#fca5a5',
      info:'#67e8f9'
    };
    el.style.color = colors[tone] || colors.muted;
  }

  function makePanelDraggable(panel, handle) {
    let dragging = false;
    let sx = 0, sy = 0, sl = 0, st = 0;

    handle.addEventListener('pointerdown', event => {
      if (event.target.closest('button')) return;
      dragging = true;
      handle.setPointerCapture?.(event.pointerId);
      const r = panel.getBoundingClientRect();
      sx = event.clientX;
      sy = event.clientY;
      sl = r.left;
      st = r.top;
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
      panel.style.left = `${sl}px`;
      panel.style.top = `${st}px`;
      event.preventDefault();
    });

    handle.addEventListener('pointermove', event => {
      if (!dragging) return;
      const maxX = Math.max(0, window.innerWidth - panel.offsetWidth);
      const maxY = Math.max(0, window.innerHeight - panel.offsetHeight);
      const x = Math.min(maxX, Math.max(0, sl + event.clientX - sx));
      const y = Math.min(maxY, Math.max(0, st + event.clientY - sy));
      panel.style.left = `${x}px`;
      panel.style.top = `${y}px`;
    });

    const end = () => { dragging = false; };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
  }

  function ensurePanel() {
    if (document.getElementById('dms43-panel')) return;

    const panel = document.createElement('div');
    panel.id = 'dms43-panel';
    panel.style.cssText = [
      'position:fixed',
      'right:12px',
      'bottom:12px',
      'z-index:2147483647',
      'width:218px',
      'padding:9px',
      'border-radius:12px',
      'background:rgba(4,12,9,.96)',
      'border:1px solid rgba(74,222,128,.32)',
      'box-shadow:0 12px 32px rgba(0,0,0,.38)',
      'font-family:Inter,Arial,sans-serif',
      'color:#f8fafc',
      'user-select:none'
    ].join(';');

    panel.innerHTML = `
      <div id="dms43-drag" style="display:flex;align-items:center;gap:6px;cursor:move">
        <span style="font-size:13px">🎥</span>
        <span style="font-size:11px;font-weight:900;color:#86efac;letter-spacing:.03em">
          PREMIUM CAPTURE
        </span>
        <span style="margin-left:auto;font-size:10px;color:#64748b">⋮⋮</span>
      </div>
      <div id="dms43-status"
           style="font-size:10px;line-height:1.3;color:#9ca3af;margin:6px 0">
        Ready to enable
      </div>
      <button id="dms43-enable"
        style="width:100%;border:0;border-radius:8px;padding:7px 8px;background:#16a34a;color:white;font-size:10px;font-weight:900;cursor:pointer">
        Enable + record setup
      </button>
      <div style="font-size:8.5px;line-height:1.25;color:#64748b;margin-top:6px">
        Select this tab and enable <b>Share tab audio</b>.
      </div>
    `;

    document.body.appendChild(panel);
    state.panel = panel;

    makePanelDraggable(panel, panel.querySelector('#dms43-drag'));
    panel.querySelector('#dms43-enable')?.addEventListener('click', enableCapture);
  }

  function hidePanelFromCapture() {
    if (state.panel) state.panel.style.display = 'none';
  }

  function restorePanel() {
    if (state.panel) state.panel.style.display = 'block';
  }

  function stopDisplayStream() {
    try {
      state.displayStream?.getTracks?.().forEach(track => track.stop());
    } catch (_) {}
    state.displayStream = null;
  }

  async function enableCapture() {
    if (!navigator.mediaDevices?.getDisplayMedia) {
      status('Use desktop Chrome/Edge', 'bad');
      return;
    }

    if (state.recorder?.state === 'recording') {
      status('Already recording', 'warn');
      return;
    }

    try {
      status('Choose this tab + Share tab audio…', 'info');

      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          frameRate: { ideal: 30, max: 30 },
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        },
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false
        },
        preferCurrentTab: true,
        selfBrowserSurface: 'include',
        surfaceSwitching: 'include',
        systemAudio: 'include'
      });

      const audioTracks = stream.getAudioTracks();

      // User specifically wants the bot's own ticking/sounds in the finished video.
      // If tab audio wasn't shared, do not silently create a soundless recording.
      if (!audioTracks.length) {
        stream.getTracks().forEach(t => t.stop());
        status('No tab audio. Enable "Share tab audio" and retry.', 'bad');
        alert(
          'DigitMatchStar video needs tab audio.\n\n' +
          'Please click Enable again, choose the DigitMatchStar TAB, ' +
          'and turn on "Share tab audio" before clicking Share.'
        );
        return;
      }

      state.displayStream = stream;

      stream.getVideoTracks()[0]?.addEventListener('ended', () => {
        if (state.recorder?.state === 'recording') {
          try { state.recorder.stop(); } catch (_) {}
        }
        state.displayStream = null;
        restorePanel();
        status('Sharing ended', 'warn');
      });

      startSessionRecorder();
    } catch (error) {
      console.warn('[DMS v4.3] capture permission failed:', error);
      status('Capture not enabled', 'bad');
    }
  }

  function startSessionRecorder() {
    if (!state.displayStream) return;

    const options = {
      videoBitsPerSecond: 8_000_000,
      audioBitsPerSecond: 160_000
    };
    const mime = supportedMime();
    if (mime) options.mimeType = mime;

    state.chunks = [];
    state.captureStartedAt = Date.now();
    state.activeCycleId = null;
    state.lastCompletedCycle = null;
    state.lastSeenCurrent = !!currentCycle();

    try {
      const recorder = new MediaRecorder(state.displayStream, options);
      state.recorder = recorder;

      recorder.ondataavailable = event => {
        if (event.data?.size) state.chunks.push(event.data);
      };

      recorder.onerror = event => {
        console.warn('[DMS v4.3] recorder error:', event);
      };

      recorder.onstop = finalizeRecording;

      // Hide the control BEFORE recording begins. It will not appear in the video.
      hidePanelFromCapture();

      recorder.start(500);

      console.log(
        '🎥 DigitMatchStar v4.3 capture started with tab audio. ' +
        'The capture UI is hidden from the footage.'
      );
    } catch (error) {
      restorePanel();
      console.warn('[DMS v4.3] recorder start failed:', error);
      status('Recorder could not start', 'bad');
    }
  }

  function observeCycle() {
    const current = currentCycle();

    if (current && !state.lastSeenCurrent) {
      state.lastSeenCurrent = true;
      state.activeCycleId = cycleId(current);
      console.log('[DMS v4.3] observed cycle start:', state.activeCycleId);
      return;
    }

    if (!current && state.lastSeenCurrent) {
      state.lastSeenCurrent = false;

      if (state.activeCycleId) {
        const completed = findCompletedCycle(state.activeCycleId);
        if (completed) state.lastCompletedCycle = completed;

        // Keep the bot's final result and sound on screen briefly.
        window.setTimeout(() => {
          if (state.recorder?.state === 'recording') {
            try { state.recorder.stop(); } catch (_) {}
          }
        }, 1800);
      }
    }
  }

  async function finalizeRecording() {
    restorePanel();

    const mime = state.recorder?.mimeType || 'video/webm';
    const blob = new Blob(state.chunks, { type: mime });

    if (state.lastBlobUrl) {
      try { URL.revokeObjectURL(state.lastBlobUrl); } catch (_) {}
    }
    state.lastBlobUrl = URL.createObjectURL(blob);

    const completed =
      state.lastCompletedCycle ||
      findCompletedCycle(state.activeCycleId);

    if (!completed) {
      status('Clip saved, but no completed cycle was found', 'bad');
      exposeDownload(blob);
      return;
    }

    const payloadCycle = clone(completed) || {};
    payloadCycle.captureStartedAt = state.captureStartedAt;
    payloadCycle.captureHadAudio = true;
    payloadCycle.captureVersion = VERSION;

    status('Uploading premium video…', 'info');

    try {
      await uploadForCompose(blob, payloadCycle);
      status('Sent to Telegram ✓', 'good');
    } catch (error) {
      console.error('[DMS v4.3] premium upload failed:', error);
      status(`Upload failed: ${error?.message || error}`, 'bad');
      exposeDownload(blob);
    }
  }

  function exposeDownload(blob) {
    if (!state.panel) return;

    let a = document.getElementById('dms43-download');
    if (!a) {
      a = document.createElement('a');
      a.id = 'dms43-download';
      a.textContent = 'Download raw clip';
      a.style.cssText = [
        'display:block',
        'margin-top:6px',
        'padding:6px',
        'border-radius:7px',
        'background:#1f2937',
        'color:#fff',
        'font-size:9px',
        'font-weight:800',
        'text-align:center',
        'text-decoration:none'
      ].join(';');
      state.panel.appendChild(a);
    }

    a.href = state.lastBlobUrl;
    a.download = `digitmatchstar-live-${state.activeCycleId || Date.now()}.webm`;
  }

  async function uploadForCompose(blob, cycle) {
    if (state.uploading) throw new Error('Upload already in progress');

    const token = getToken();
    const accountId = getAccountId();
    const id = cycleId(cycle);

    if (!token) throw new Error('Deriv token unavailable');
    if (!accountId) throw new Error('Deriv account ID unavailable');
    if (!id) throw new Error('Cycle ID unavailable');

    state.uploading = true;

    try {
      const ticketResponse = await fetch('/api/live-capture-ticket', {
        method: 'POST',
        headers: {
          'Content-Type':'application/json',
          'Authorization':`Bearer ${token}`
        },
        body: JSON.stringify({
          account_id: accountId,
          cycle_id: id,
          theme: 'ultra-premium-v4-3'
        })
      });

      const ticketData = await ticketResponse.json().catch(() => ({}));

      if (!ticketResponse.ok) {
        throw new Error(
          ticketData?.error ||
          `Upload ticket failed (HTTP ${ticketResponse.status})`
        );
      }

      if (!ticketData?.uploadUrl || !ticketData?.ticket) {
        throw new Error('Media-worker ticket response is incomplete');
      }

      const form = new FormData();
      form.append('video', blob, `digitmatchstar-${id}.webm`);
      form.append('ticket', ticketData.ticket);
      form.append('cycle', JSON.stringify(cycle));
      form.append('website', 'https://www.digitmatchstar.com');

      let workerResponse;
      try {
        workerResponse = await fetch(ticketData.uploadUrl, {
          method:'POST',
          body:form,
          mode:'cors'
        });
      } catch (networkError) {
        throw new Error(
          'Cannot reach media worker. Check Render is LIVE and CORS is deployed.'
        );
      }

      const result = await workerResponse.json().catch(() => ({}));

      if (!workerResponse.ok) {
        throw new Error(
          result?.detail ||
          result?.error ||
          `Media worker failed (HTTP ${workerResponse.status})`
        );
      }

      window.__dmsLastPremiumVideo = result;
      return result;
    } finally {
      state.uploading = false;
    }
  }

  function boot() {
    ensurePanel();

    state.observerTimer = window.setInterval(observeCycle, 200);

    console.log(
      `🎥 DigitMatchStar Premium Capture ${VERSION} loaded. ` +
      'Read-only observer; trading logic untouched.'
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once:true });
  } else {
    boot();
  }

  window.dmsPremiumCapture = {
    version: VERSION,
    enable: enableCapture,
    getState: () => ({
      recording: state.recorder?.state === 'recording',
      captureStartedAt: state.captureStartedAt,
      activeCycleId: state.activeCycleId,
      hasAudio: !!state.displayStream?.getAudioTracks?.().length,
      uploading: state.uploading
    })
  };
})();
