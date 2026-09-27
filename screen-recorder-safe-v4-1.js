/*
 * DigitMatchStar Safe Live Observer v4.1
 * NON-INVASIVE recorder for the production bot-obfuscated.html.
 *
 * Design rule:
 * - DOES NOT replace, monkey-patch, wrap, or call trading functions.
 * - DOES NOT alter cyclePerformance.startCycle / completeCycle.
 * - DOES NOT alter WebSocket handlers, buy/proposal functions, stake logic, or risk logic.
 * - ONLY reads public cycle state and records the browser tab.
 *
 * The trading bot continues independently if this recorder fails.
 */
(() => {
  'use strict';

  const OBSERVER_VERSION = '4.1-safe-observer';

  const state = {
    displayStream: null,
    recorder: null,
    chunks: [],
    activeCycleId: null,
    activeCycleSnapshot: null,
    lastCompletedSnapshot: null,
    lastBlob: null,
    lastUrl: null,
    uploading: false,
    observerTimer: null,
    lastSeenCurrent: false,
    lastHistoryKey: null
  };

  function clone(value) {
    try { return JSON.parse(JSON.stringify(value)); }
    catch (_) { return null; }
  }

  function getCyclePerformance() {
    // Read only. Never assign into this object.
    const cp = window.cyclePerformance;
    return cp && typeof cp === 'object' ? cp : null;
  }

  function getCurrentCycle() {
    const cp = getCyclePerformance();
    if (!cp) return null;
    return cp.current && typeof cp.current === 'object' ? cp.current : null;
  }

  function getHistoryArray() {
    const cp = getCyclePerformance();
    if (!cp) return [];
    if (Array.isArray(cp.history)) return cp.history;
    if (Array.isArray(cp.cycles)) return cp.cycles;
    if (Array.isArray(cp.completed)) return cp.completed;
    return [];
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

  function supportedMime() {
    return [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm'
    ].find(type => window.MediaRecorder?.isTypeSupported?.(type)) || '';
  }

  function getAccountId() {
    const mode = String(localStorage.getItem('selectedAccountMode') || 'DEMO').toUpperCase();
    return (
      localStorage.getItem('active_account') ||
      localStorage.getItem('derivAccount') ||
      localStorage.getItem(mode === 'REAL' ? 'derivRealAccount' : 'derivDemoAccount') ||
      window.DERIV_ACCOUNT_ID ||
      window.accountId ||
      ''
    );
  }

  function getToken() {
    if (typeof window.getStoredDerivToken === 'function') {
      try {
        const t = window.getStoredDerivToken();
        if (t) return t;
      } catch (_) {}
    }
    return (
      window.DERIV_TOKEN ||
      localStorage.getItem('deriv_token') ||
      localStorage.getItem('derivToken') ||
      localStorage.getItem('authToken') ||
      ''
    );
  }

  function ensurePanel() {
    if (document.getElementById('dms-safe-live-observer')) return;

    const el = document.createElement('div');
    el.id = 'dms-safe-live-observer';
    el.style.cssText = [
      'position:fixed',
      'right:18px',
      'bottom:18px',
      'z-index:999999',
      'width:330px',
      'padding:14px',
      'border-radius:18px',
      'background:rgba(4,12,9,.97)',
      'border:1px solid rgba(74,222,128,.42)',
      'box-shadow:0 18px 60px rgba(0,0,0,.55)',
      'font-family:Inter,Arial,sans-serif',
      'color:#f7faf8'
    ].join(';');

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;font-weight:900;color:#4ade80;font-size:14px">
        <span>🎥</span><span>SAFE LIVE CAPTURE</span>
      </div>

      <div style="margin:5px 0 9px;font-size:10px;color:#86efac;font-weight:800">
        READ-ONLY OBSERVER · TRADING LOGIC UNTOUCHED
      </div>

      <div id="dms-safe-status" style="font-size:12px;color:#9db1a6;margin:7px 0 10px">
        Observer loaded · capture permission not enabled
      </div>

      <button id="dms-safe-enable"
        style="width:100%;padding:10px;border:0;border-radius:11px;background:#16a34a;color:#fff;font-weight:900;cursor:pointer">
        Enable live capture
      </button>

      <div id="dms-safe-rec"
        style="display:none;margin-top:8px;color:#86efac;font-size:12px;font-weight:800">
        ● RECORDING ACTUAL BOT SCREEN
      </div>

      <div id="dms-safe-upload"
        style="display:none;margin-top:8px;color:#67e8f9;font-size:12px;font-weight:800">
        ↑ BUILDING PREMIUM VIDEO…
      </div>

      <video id="dms-safe-preview" controls playsinline
        style="display:none;width:100%;margin-top:10px;border-radius:11px;background:#000"></video>

      <a id="dms-safe-download"
        style="display:none;margin-top:8px;padding:8px 10px;border-radius:9px;background:#1f2937;color:#fff;text-align:center;text-decoration:none;font-size:12px;font-weight:800">
        Download raw live clip
      </a>

      <div style="font-size:10px;line-height:1.4;color:#738078;margin-top:9px">
        Chrome/Edge requires you to click Enable live capture before any screen can be recorded.
      </div>
    `;

    document.body.appendChild(el);

    document
      .getElementById('dms-safe-enable')
      ?.addEventListener('click', enableCapture);
  }

  function setStatus(text, color = '#9db1a6') {
    const el = document.getElementById('dms-safe-status');
    if (!el) return;
    el.textContent = text;
    el.style.color = color;
  }

  async function enableCapture() {
    if (!navigator.mediaDevices?.getDisplayMedia) {
      alert('Use a current Chrome or Edge browser for tab recording.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 30, max: 30 } },
        audio: false,
        preferCurrentTab: true,
        selfBrowserSurface: 'include',
        surfaceSwitching: 'include'
      });

      state.displayStream = stream;

      const track = stream.getVideoTracks()[0];
      if (track) {
        track.addEventListener('ended', () => {
          state.displayStream = null;
          setStatus('Screen sharing ended · click Enable live capture again', '#fca5a5');
          const btn = document.getElementById('dms-safe-enable');
          if (btn) btn.textContent = 'Enable live capture';
        });
      }

      const btn = document.getElementById('dms-safe-enable');
      if (btn) btn.textContent = 'Capture enabled ✓';

      setStatus('Ready · safely observing next cycle', '#86efac');
    } catch (err) {
      console.warn('[DMS observer] capture permission not granted:', err);
      setStatus('Capture permission not enabled', '#fca5a5');
    }
  }

  function startRecording(cycle) {
    // This function only touches MediaRecorder state.
    if (!state.displayStream) return;
    if (state.recorder?.state === 'recording') return;

    const id = cycleId(cycle);
    if (!id) return;

    const mime = supportedMime();
    const options = { videoBitsPerSecond: 7_500_000 };
    if (mime) options.mimeType = mime;

    state.chunks = [];
    state.activeCycleId = id;
    state.activeCycleSnapshot = clone(cycle);

    try {
      const recorder = new MediaRecorder(state.displayStream, options);
      state.recorder = recorder;

      recorder.ondataavailable = event => {
        if (event.data && event.data.size > 0) {
          state.chunks.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const blob = new Blob(
          state.chunks,
          { type: recorder.mimeType || 'video/webm' }
        );

        state.lastBlob = blob;

        if (state.lastUrl) {
          try { URL.revokeObjectURL(state.lastUrl); } catch (_) {}
        }

        state.lastUrl = URL.createObjectURL(blob);

        const preview = document.getElementById('dms-safe-preview');
        const download = document.getElementById('dms-safe-download');
        const rec = document.getElementById('dms-safe-rec');

        if (preview) {
          preview.src = state.lastUrl;
          preview.style.display = 'block';
        }

        if (download) {
          download.href = state.lastUrl;
          download.download =
            `digitmatchstar-live-${String(state.activeCycleId || Date.now())
              .replace(/[^a-z0-9_-]/gi, '-')}.webm`;
          download.style.display = 'block';
        }

        if (rec) rec.style.display = 'none';

        setStatus(
          `Raw live clip ready · ${(blob.size / 1024 / 1024).toFixed(1)} MB`,
          '#86efac'
        );

        const completed =
          state.lastCompletedSnapshot ||
          findCompletedCycle(state.activeCycleId) ||
          state.activeCycleSnapshot;

        if (completed) {
          try {
            await uploadForCompose(blob, completed);
          } catch (err) {
            console.warn('[DMS observer] premium upload failed:', err);
            setStatus('Raw clip saved · premium upload failed', '#fca5a5');
          }
        } else {
          console.warn('[DMS observer] no completed cycle metadata was found.');
          setStatus('Raw clip saved · cycle metadata unavailable', '#fca5a5');
        }

        state.activeCycleId = null;
        state.activeCycleSnapshot = null;
        state.lastCompletedSnapshot = null;
      };

      recorder.start(500);

      const rec = document.getElementById('dms-safe-rec');
      if (rec) rec.style.display = 'block';

      setStatus(`Recording observed cycle ${id}`, '#4ade80');
    } catch (err) {
      console.warn('[DMS observer] recorder start failed:', err);
      setStatus('Recorder could not start', '#fca5a5');
    }
  }

  function stopRecording() {
    if (state.recorder?.state === 'recording') {
      try {
        // Leave a short visual tail so the final result is visible.
        setTimeout(() => {
          if (state.recorder?.state === 'recording') {
            state.recorder.stop();
          }
        }, 1600);
      } catch (_) {}
    }
  }

  function findCompletedCycle(id) {
    if (!id) return null;

    const history = getHistoryArray();
    for (let i = history.length - 1; i >= 0; i--) {
      if (cycleId(history[i]) === String(id)) {
        return clone(history[i]);
      }
    }

    // Some implementations retain lastComplete / lastCompleted.
    const cp = getCyclePerformance();
    const candidates = [
      cp?.lastCompleted,
      cp?.lastComplete,
      cp?.lastCycle,
      cp?.latest
    ];

    for (const item of candidates) {
      if (item && cycleId(item) === String(id)) {
        return clone(item);
      }
    }

    return null;
  }

  function newestCompletedCycle() {
    const history = getHistoryArray();
    if (history.length) {
      return clone(history[history.length - 1]);
    }

    const cp = getCyclePerformance();
    return clone(
      cp?.lastCompleted ||
      cp?.lastComplete ||
      cp?.lastCycle ||
      null
    );
  }

  function completedKey(cycle) {
    if (!cycle) return '';
    return [
      cycleId(cycle),
      cycle?.status ?? '',
      cycle?.endedAt ?? cycle?.endTime ?? '',
      cycle?.winningTradeNumber ?? ''
    ].join('|');
  }

  function observeOnce() {
    // READ-ONLY. Never assign into cyclePerformance.
    const current = getCurrentCycle();

    // Transition: no cycle -> cycle
    if (current && !state.lastSeenCurrent) {
      state.lastSeenCurrent = true;

      if (state.displayStream) {
        startRecording(current);
      } else {
        setStatus(
          'Cycle detected · enable live capture before the next cycle',
          '#fbbf24'
        );
      }
      return;
    }

    // A different current cycle appeared unexpectedly.
    if (
      current &&
      state.lastSeenCurrent &&
      state.activeCycleId &&
      cycleId(current) &&
      cycleId(current) !== state.activeCycleId
    ) {
      // We do not touch the bot. We simply end our own recording.
      state.lastCompletedSnapshot = findCompletedCycle(state.activeCycleId);
      stopRecording();
      state.lastSeenCurrent = true;
      return;
    }

    // Transition: cycle -> no cycle
    if (!current && state.lastSeenCurrent) {
      state.lastSeenCurrent = false;

      const completed =
        findCompletedCycle(state.activeCycleId) ||
        newestCompletedCycle();

      if (completed) {
        state.lastCompletedSnapshot = completed;
      }

      stopRecording();
      return;
    }

    // Observe newly completed history without controlling anything.
    const latest = newestCompletedCycle();
    const key = completedKey(latest);
    if (key && key !== state.lastHistoryKey) {
      state.lastHistoryKey = key;

      if (
        state.activeCycleId &&
        cycleId(latest) === state.activeCycleId
      ) {
        state.lastCompletedSnapshot = latest;
      }
    }
  }

  async function uploadForCompose(blob, cycle) {
    if (state.uploading) return;

    const accountId = getAccountId();
    const token = getToken();
    const id = cycleId(cycle);

    if (!accountId || !token || !id) {
      throw new Error('Missing account, token, or cycle id for premium upload');
    }

    state.uploading = true;

    const uploadEl = document.getElementById('dms-safe-upload');
    if (uploadEl) uploadEl.style.display = 'block';

    setStatus('Authorizing secure premium upload…', '#67e8f9');

    try {
      const ticketResponse = await fetch('/api/live-capture-ticket', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          account_id: accountId,
          cycle_id: id,
          theme: 'ultra-premium'
        })
      });

      const ticketData = await ticketResponse.json().catch(() => ({}));

      if (!ticketResponse.ok) {
        throw new Error(
          ticketData?.error || `Ticket HTTP ${ticketResponse.status}`
        );
      }

      setStatus('Uploading actual screen capture…', '#67e8f9');

      const form = new FormData();
      form.append('video', blob, `dms-live-${id}.webm`);
      form.append('ticket', ticketData.ticket);
      form.append('cycle', JSON.stringify(cycle));
      form.append('website', 'https://www.digitmatchstar.com');

      const uploadResponse = await fetch(ticketData.uploadUrl, {
        method: 'POST',
        body: form
      });

      const uploadData = await uploadResponse.json().catch(() => ({}));

      if (!uploadResponse.ok) {
        throw new Error(
          uploadData?.detail ||
          uploadData?.error ||
          `Upload HTTP ${uploadResponse.status}`
        );
      }

      window.__dmsLastSafePremiumResult = uploadData;

      setStatus(
        'Premium video sent privately to Telegram ✓',
        '#86efac'
      );
    } finally {
      state.uploading = false;
      if (uploadEl) uploadEl.style.display = 'none';
    }
  }

  function startObserver() {
    if (state.observerTimer) return;

    // Polling is deliberately read-only and low-frequency.
    state.observerTimer = window.setInterval(observeOnce, 250);

    console.log(
      `🎥 DigitMatchStar Safe Live Observer ${OBSERVER_VERSION} loaded. ` +
      'Trading functions were not modified.'
    );
  }

  function boot() {
    ensurePanel();
    startObserver();

    // Purely informational check.
    const cp = getCyclePerformance();
    if (!cp) {
      setStatus(
        'Observer loaded · waiting for cyclePerformance state',
        '#fbbf24'
      );
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  // Public recorder API only. No trading APIs are exposed or modified.
  window.dmsSafeLiveObserver = {
    version: OBSERVER_VERSION,
    enableCapture,
    getState: () => ({
      captureEnabled: !!state.displayStream,
      recording: state.recorder?.state === 'recording',
      activeCycleId: state.activeCycleId,
      uploading: state.uploading
    })
  };
})();
