/*
 * DigitMatchStar Safe Live Observer v4.2
 * For production bot-obfuscated.html (V17-compatible).
 *
 * NON-INVASIVE:
 * - never replaces or wraps trading functions
 * - never writes to cyclePerformance
 * - never calls startCycle/completeCycle/buy/proposal
 * - only reads cycle state and records the visible browser tab
 */
(() => {
  'use strict';

  const VERSION = '4.2-safe-observer';

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
    lastSeenCurrent: false
  };

  const clone = v => {
    try { return JSON.parse(JSON.stringify(v)); }
    catch (_) { return null; }
  };

  function cp() {
    const x = window.cyclePerformance;
    return x && typeof x === 'object' ? x : null;
  }

  function currentCycle() {
    const x = cp();
    return x?.current && typeof x.current === 'object' ? x.current : null;
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

  /*
   * Production V17 stores completed cycles under:
   * cyclePerformance.historyBySymbol[symbol] = [...]
   *
   * Keep legacy fallbacks too so the recorder remains compatible.
   */
  function allHistory() {
    const x = cp();
    if (!x) return [];

    const rows = [];

    if (x.historyBySymbol && typeof x.historyBySymbol === 'object') {
      for (const value of Object.values(x.historyBySymbol)) {
        if (Array.isArray(value)) rows.push(...value);
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

  function newestCompletedCycle() {
    const rows = allHistory();
    if (rows.length) {
      const sorted = rows.slice().sort((a,b) =>
        Number(a?.endedAt || a?.startedAt || 0) -
        Number(b?.endedAt || b?.startedAt || 0)
      );
      return clone(sorted[sorted.length - 1]);
    }

    const x = cp();
    return clone(x?.lastCompleted || x?.lastComplete || x?.lastCycle || null);
  }

  function supportedMime() {
    return [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm'
    ].find(type => window.MediaRecorder?.isTypeSupported?.(type)) || '';
  }

  function getAccountId() {
    const mode = String(
      localStorage.getItem('selectedAccountMode') || 'DEMO'
    ).toUpperCase();

    return (
      (typeof window.getStoredDerivAccount === 'function'
        ? (() => { try { return window.getStoredDerivAccount() || ''; } catch (_) { return ''; } })()
        : '') ||
      localStorage.getItem('active_account') ||
      localStorage.getItem('derivAccount') ||
      localStorage.getItem(mode === 'REAL' ? 'derivRealAccount' : 'derivDemoAccount') ||
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
      localStorage.getItem('active_token') ||
      localStorage.getItem('derivToken') ||
      localStorage.getItem('deriv_token') ||
      localStorage.getItem('derivTokenDemo') ||
      localStorage.getItem('derivTokenReal') ||
      localStorage.getItem('authToken') ||
      ''
    );
  }

  function ensurePanel() {
    if (document.getElementById('dms-safe-live-observer')) return;

    const el = document.createElement('div');
    el.id = 'dms-safe-live-observer';
    el.style.cssText = [
      'position:fixed','right:18px','bottom:18px','z-index:999999',
      'width:330px','padding:14px','border-radius:18px',
      'background:rgba(4,12,9,.97)',
      'border:1px solid rgba(74,222,128,.42)',
      'box-shadow:0 18px 60px rgba(0,0,0,.55)',
      'font-family:Inter,Arial,sans-serif','color:#f7faf8'
    ].join(';');

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;font-weight:900;color:#4ade80;font-size:14px">
        <span>🎥</span><span>SAFE LIVE CAPTURE</span>
      </div>
      <div style="margin:5px 0 9px;font-size:10px;color:#86efac;font-weight:800">
        V4.2 · READ-ONLY · TRADING LOGIC UNTOUCHED
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
        Use desktop Chrome/Edge. Click Enable before the next cycle.
      </div>
    `;

    document.body.appendChild(el);
    document.getElementById('dms-safe-enable')
      ?.addEventListener('click', enableCapture);
  }

  function setStatus(text, color='#9db1a6') {
    const el = document.getElementById('dms-safe-status');
    if (!el) return;
    el.textContent = text;
    el.style.color = color;
  }

  async function enableCapture() {
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setStatus('This browser cannot record the tab · use desktop Chrome/Edge', '#fca5a5');
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

      stream.getVideoTracks()[0]?.addEventListener('ended', () => {
        state.displayStream = null;
        const btn = document.getElementById('dms-safe-enable');
        if (btn) btn.textContent = 'Enable live capture';
        setStatus('Screen sharing ended · enable again', '#fca5a5');
      });

      const btn = document.getElementById('dms-safe-enable');
      if (btn) btn.textContent = 'Capture enabled ✓';

      setStatus('Ready · safely observing next cycle', '#86efac');
    } catch (err) {
      console.warn('[DMS video] capture permission:', err);
      setStatus('Capture permission not enabled', '#fca5a5');
    }
  }

  function startRecording(cycle) {
    if (!state.displayStream) return;
    if (state.recorder?.state === 'recording') return;

    const id = cycleId(cycle);
    if (!id) {
      setStatus('Cycle detected but cycle ID is unavailable', '#fca5a5');
      return;
    }

    const opts = { videoBitsPerSecond: 7_500_000 };
    const mime = supportedMime();
    if (mime) opts.mimeType = mime;

    state.activeCycleId = id;
    state.activeCycleSnapshot = clone(cycle);
    state.lastCompletedSnapshot = null;
    state.chunks = [];

    try {
      const recorder = new MediaRecorder(state.displayStream, opts);
      state.recorder = recorder;

      recorder.ondataavailable = e => {
        if (e.data?.size) state.chunks.push(e.data);
      };

      recorder.onstop = async () => {
        const blob = new Blob(state.chunks, {
          type: recorder.mimeType || 'video/webm'
        });

        state.lastBlob = blob;
        if (state.lastUrl) {
          try { URL.revokeObjectURL(state.lastUrl); } catch (_) {}
        }
        state.lastUrl = URL.createObjectURL(blob);

        const preview = document.getElementById('dms-safe-preview');
        const download = document.getElementById('dms-safe-download');
        const rec = document.getElementById('dms-safe-rec');

        if (rec) rec.style.display = 'none';

        if (preview) {
          preview.src = state.lastUrl;
          preview.style.display = 'block';
        }

        if (download) {
          download.href = state.lastUrl;
          download.download =
            `digitmatchstar-live-${String(state.activeCycleId || Date.now())
              .replace(/[^a-z0-9_-]/gi,'-')}.webm`;
          download.style.display = 'block';
        }

        setStatus(
          `Raw live clip ready · ${(blob.size/1024/1024).toFixed(1)} MB`,
          '#86efac'
        );

        // By now V17 has saved the completed cycle into historyBySymbol
        const completed =
          state.lastCompletedSnapshot ||
          findCompletedCycle(state.activeCycleId) ||
          newestCompletedCycle();

        if (!completed || cycleId(completed) !== String(state.activeCycleId)) {
          setStatus('Raw clip saved · completed cycle metadata not found', '#fca5a5');
        } else {
          try {
            await uploadForCompose(blob, completed);
          } catch (err) {
            console.warn('[DMS video] upload/composition failed:', err);
            setStatus(
              `Raw clip saved · premium upload failed: ${err?.message || err}`,
              '#fca5a5'
            );
          }
        }

        state.activeCycleId = null;
        state.activeCycleSnapshot = null;
        state.lastCompletedSnapshot = null;
      };

      recorder.start(500);
      const rec = document.getElementById('dms-safe-rec');
      if (rec) rec.style.display = 'block';

      setStatus(`Recording cycle ${id}`, '#4ade80');
    } catch (err) {
      console.warn('[DMS video] MediaRecorder:', err);
      setStatus('Recorder could not start', '#fca5a5');
    }
  }

  function stopRecording() {
    if (state.recorder?.state !== 'recording') return;

    // Keep final bot result visible briefly.
    window.setTimeout(() => {
      if (state.recorder?.state === 'recording') {
        try { state.recorder.stop(); } catch (_) {}
      }
    }, 1600);
  }

  function observeOnce() {
    const current = currentCycle();

    if (current && !state.lastSeenCurrent) {
      state.lastSeenCurrent = true;

      if (state.displayStream) {
        startRecording(current);
      } else {
        setStatus('Cycle detected · enable capture before the next cycle', '#fbbf24');
      }
      return;
    }

    if (!current && state.lastSeenCurrent) {
      state.lastSeenCurrent = false;

      const completed =
        findCompletedCycle(state.activeCycleId) ||
        newestCompletedCycle();

      if (
        completed &&
        state.activeCycleId &&
        cycleId(completed) === String(state.activeCycleId)
      ) {
        state.lastCompletedSnapshot = completed;
      }

      stopRecording();
    }
  }

  async function uploadForCompose(blob, cycle) {
    if (state.uploading) return;

    const token = getToken();
    const accountId = getAccountId();
    const id = cycleId(cycle);

    if (!token) throw new Error('Deriv token unavailable');
    if (!accountId) throw new Error('Deriv account ID unavailable');
    if (!id) throw new Error('Cycle ID unavailable');

    state.uploading = true;
    const uploadEl = document.getElementById('dms-safe-upload');
    if (uploadEl) uploadEl.style.display = 'block';

    try {
      setStatus('Requesting secure upload ticket…', '#67e8f9');

      const ticketRes = await fetch('/api/live-capture-ticket', {
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

      const ticket = await ticketRes.json().catch(() => ({}));
      if (!ticketRes.ok) {
        throw new Error(ticket?.error || `ticket HTTP ${ticketRes.status}`);
      }

      if (!ticket?.uploadUrl || !ticket?.ticket) {
        throw new Error('Ticket response is incomplete');
      }

      setStatus('Uploading actual screen capture to media worker…', '#67e8f9');

      const form = new FormData();
      form.append('video', blob, `dms-live-${id}.webm`);
      form.append('ticket', ticket.ticket);
      form.append('cycle', JSON.stringify(cycle));
      form.append('website', 'https://www.digitmatchstar.com');

      const uploadRes = await fetch(ticket.uploadUrl, {
        method: 'POST',
        body: form
      });

      const result = await uploadRes.json().catch(() => ({}));
      if (!uploadRes.ok) {
        throw new Error(
          result?.detail || result?.error || `worker HTTP ${uploadRes.status}`
        );
      }

      window.__dmsLastSafePremiumResult = result;
      setStatus('Premium video sent privately to Telegram ✓', '#86efac');
    } finally {
      state.uploading = false;
      if (uploadEl) uploadEl.style.display = 'none';
    }
  }

  function boot() {
    ensurePanel();

    state.observerTimer = window.setInterval(observeOnce, 250);

    if (!cp()) {
      setStatus('Observer loaded · waiting for cyclePerformance', '#fbbf24');
    }

    console.log(
      `🎥 DigitMatchStar Safe Live Observer ${VERSION} loaded. ` +
      'No trading function was modified.'
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once:true });
  } else {
    boot();
  }

  window.dmsSafeLiveObserver = {
    version: VERSION,
    enableCapture,
    getState: () => ({
      captureEnabled: !!state.displayStream,
      recording: state.recorder?.state === 'recording',
      activeCycleId: state.activeCycleId,
      uploading: state.uploading,
      completedHistoryRows: allHistory().length
    })
  };
})();
