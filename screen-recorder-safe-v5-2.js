/*
 * DigitMatchStar Premium Capture v5.0
 * READ-ONLY observer. Does not patch or replace trading functions.
 *
 * Adds:
 * - capture-friendly view preparation
 * - full event timeline for premium guided videos
 * - snapshots of target digit, mode, trade count, stake, P/L and status
 * - tab audio requirement
 * - hidden capture controls while recording
 */
(() => {
  'use strict';

  const VERSION = '5.7-dynamic-pnl-win-hold';

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
    lastBlobUrl: null,
    events: [],
    lastFingerprint: '',
    lastTradeCount: 0,
    lastTargetDigit: null,
    lastActiveContractId: null,
    savedView: null,
    capturePrepared: false,
    stopPending: false
  };

  function removeLegacyRecorderPanels() {
    const legacyIds = [
      'dms43-panel',
      'dms42-panel',
      'dms41-panel',
      'dms40-panel'
    ];
    for (const id of legacyIds) {
      try { document.getElementById(id)?.remove(); } catch (_) {}
    }

    // Permanent safety net: if an old cached recorder script runs later,
    // its panel remains hidden.
    if (!document.getElementById('dms-single-recorder-guard')) {
      const style = document.createElement('style');
      style.id = 'dms-single-recorder-guard';
      style.textContent = `
        #dms43-panel,
        #dms42-panel,
        #dms41-panel,
        #dms40-panel {
          display: none !important;
          visibility: hidden !important;
          pointer-events: none !important;
        }
      `;
      document.head.appendChild(style);
    }
  }

  function enforceSingleRecorderWindow() {
    removeLegacyRecorderPanels();

    // Catch a legacy script that loads slightly after this recorder.
    let passes = 0;
    const timer = setInterval(() => {
      removeLegacyRecorderPanels();
      passes += 1;
      if (passes >= 24) clearInterval(timer); // ~6 seconds
    }, 250);
  }


  const clone = value => {
    try { return JSON.parse(JSON.stringify(value)); }
    catch (_) { return null; }
  };

  const text = id => String(document.getElementById(id)?.textContent || '').trim();

  function numberFromText(value) {
    const n = Number(String(value ?? '').replace(/[^0-9+.-]/g, ''));
    return Number.isFinite(n) ? n : null;
  }

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
    for (const key of ['history', 'cycles', 'completed']) {
      if (Array.isArray(x[key])) rows.push(...x[key]);
    }
    return rows.filter(Boolean);
  }

  function findCompletedCycle(id) {
    if (!id) return null;
    const rows = allHistory();
    for (let i = rows.length - 1; i >= 0; i--) {
      if (cycleId(rows[i]) === String(id)) return clone(rows[i]);
    }
    const x = cp();
    for (const item of [x?.lastCompleted, x?.lastComplete, x?.lastCycle, x?.latest]) {
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
    const mode = String(localStorage.getItem('selectedAccountMode') || 'DEMO').toUpperCase();
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

  function status(message, tone='muted') {
    const el = document.getElementById('dms50-status');
    if (!el) return;
    el.textContent = message;
    const colors = {
      muted:'#9ca3af', good:'#86efac', warn:'#fcd34d',
      bad:'#fca5a5', info:'#67e8f9'
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
      sx = event.clientX; sy = event.clientY; sl = r.left; st = r.top;
      panel.style.right = 'auto'; panel.style.bottom = 'auto';
      panel.style.left = `${sl}px`; panel.style.top = `${st}px`;
      event.preventDefault();
    });
    handle.addEventListener('pointermove', event => {
      if (!dragging) return;
      const maxX = Math.max(0, innerWidth - panel.offsetWidth);
      const maxY = Math.max(0, innerHeight - panel.offsetHeight);
      panel.style.left = `${Math.min(maxX, Math.max(0, sl + event.clientX - sx))}px`;
      panel.style.top = `${Math.min(maxY, Math.max(0, st + event.clientY - sy))}px`;
    });
    const end = () => { dragging = false; };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
  }

  function ensurePanel() {
    if (document.getElementById('dms50-panel')) return;
    const panel = document.createElement('div');
    panel.id = 'dms50-panel';
    panel.style.cssText = [
      'position:fixed','right:12px','bottom:12px','z-index:2147483647',
      'width:218px','padding:9px','border-radius:12px',
      'background:rgba(4,12,9,.96)','border:1px solid rgba(74,222,128,.32)',
      'box-shadow:0 12px 32px rgba(0,0,0,.38)',
      'font-family:Inter,Arial,sans-serif','color:#f8fafc','user-select:none'
    ].join(';');
    panel.innerHTML = `
      <div id="dms50-drag" style="display:flex;align-items:center;gap:6px;cursor:move">
        <span style="font-size:13px">🎥</span>
        <span style="font-size:11px;font-weight:900;color:#86efac;letter-spacing:.03em">
          PREMIUM CAPTURE V5
        </span>
        <span style="margin-left:auto;font-size:10px;color:#64748b">⋮⋮</span>
      </div>
      <div id="dms50-status" style="font-size:10px;line-height:1.3;color:#9ca3af;margin:6px 0">
        Ready
      </div>
      <button id="dms50-enable"
        style="width:100%;border:0;border-radius:8px;padding:7px 8px;background:#16a34a;color:white;font-size:10px;font-weight:900;cursor:pointer">
        Prepare + record
      </button>
      <div style="font-size:8.5px;line-height:1.25;color:#64748b;margin-top:6px">
        Choose this tab and enable <b>Share tab audio</b>.
      </div>`;
    document.body.appendChild(panel);
    state.panel = panel;
    makePanelDraggable(panel, panel.querySelector('#dms50-drag'));
    panel.querySelector('#dms50-enable')?.addEventListener('click', enableCapture);
  }

  function prepareCaptureView() {
    if (state.capturePrepared) return;
    state.savedView = {
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      htmlZoom: document.documentElement.style.zoom || '',
      bodyZoom: document.body?.style?.zoom || ''
    };

    // Visual-only preparation. This never touches trading state.
    // Slightly zoom out so mode controls + metrics + status fit in the browser viewport.
    document.documentElement.style.zoom = '0.94';

    const anchor =
      document.getElementById('mode_instant') ||
      document.getElementById('mode_ai') ||
      document.getElementById('predictedDigit') ||
      document.getElementById('trade-result-container');

    try {
      anchor?.scrollIntoView?.({ block:'center', inline:'nearest', behavior:'instant' });
      window.scrollBy({ top:-120, left:0, behavior:'instant' });
    } catch (_) {
      anchor?.scrollIntoView?.();
      window.scrollBy(0, -120);
    }

    state.capturePrepared = true;
  }

  function restoreCaptureView() {
    if (!state.savedView) return;
    document.documentElement.style.zoom = state.savedView.htmlZoom;
    if (document.body) document.body.style.zoom = state.savedView.bodyZoom;
    window.scrollTo(state.savedView.scrollX, state.savedView.scrollY);
    state.savedView = null;
    state.capturePrepared = false;
  }

  function hidePanelFromCapture() {
    if (state.panel) state.panel.style.display = 'none';
  }

  function restorePanel() {
    if (state.panel) state.panel.style.display = 'block';
  }


  function readBotPnl() {
    // Mirror the exact P/L visible on the bot first.
    const displayed = numberFromText(text('metricTotalProfit'));
    if (displayed !== null) return displayed;

    const liveNet = Number(window.netProfit);
    if (Number.isFinite(liveNet)) return liveNet;

    const cycleNet = Number(window.cyclePerformance?.current?.netPnL);
    if (Number.isFinite(cycleNet)) return cycleNet;

    return 0;
  }

  function snapshot() {
    const target = Number(document.getElementById('predictedDigit')?.value);
    const mode = window.sessionState?.mode ||
      (document.getElementById('mode_ai')?.classList.contains('bg-green-600') ? 'ai' : 'instant');

    return {
      atMs: state.captureStartedAt ? Math.max(0, Date.now() - state.captureStartedAt) : 0,
      mode: String(mode || ''),
      targetDigit: Number.isFinite(target) ? target : null,
      currentDigit: numberFromText(text('metricLastDigit')),
      currentTick: text('metricLiveTick'),
      tradeCount: Number(window.tradeCount ?? numberFromText(text('metricTradeCount')) ?? 0),
      stake: Number(window.currentStake ?? numberFromText(text('metricCurrentStake')) ?? 0),
      pnl: readBotPnl(),
      result: text('metricTradeResult'),
      status: text('metricPreviousResult'),
      action: text('metricNextAction'),
      activeContractId: window.activeContract?.contractId ?? null
    };
  }

  function addEvent(type, title, subtitle='', extra={}) {
    if (!state.captureStartedAt) return;
    const s = snapshot();
    const event = {
      type,
      title,
      subtitle,
      ...s,
      ...extra
    };
    const fp = JSON.stringify([
      type, title, subtitle,
      event.tradeCount, event.targetDigit,
      event.activeContractId, event.result, event.status, event.action
    ]);
    if (fp === state.lastFingerprint) return;
    state.lastFingerprint = fp;
    state.events.push(event);
    if (state.events.length > 180) state.events.shift();
    console.log('[DMS v5 event]', event);
  }

  function classifyStatus(s) {
    const joined = `${s.result} ${s.status} ${s.action}`.toUpperCase();

    if (/WIN CONFIRMED|DIGIT MATCH|FAST MATCH|MATCHED/.test(joined)) {
      return ['matched', 'DIGIT MATCHED', `Target digit ${s.targetDigit ?? '-'} matched`];
    }
    if (/LOSS CONFIRMED|RECONCILED LOSS/.test(joined)) {
      return ['loss_confirmed', 'NO MATCH · RECOVERY READY', `Trade ${s.tradeCount} confirmed as a miss`];
    }
    if (/VERIFYING RESULT|POSSIBLE LOSS|WAITING FOR DERIV/.test(joined)) {
      return ['verifying', 'VERIFYING RESULT', 'Waiting for Deriv confirmation'];
    }
    if (/CONTRACT OPEN|WATCHING NEXT TICK/.test(joined)) {
      return ['trade_open', `TRADE ${Math.max(1, s.tradeCount)} EXECUTING`, `Target digit ${s.targetDigit ?? '-'} · watching the next tick`];
    }
    if (/RECOVERY CHECK|RECOVERY ENTRY|RECOVERY/.test(joined)) {
      return ['recovery', 'RECOVERY ENTRY', `Preparing trade ${Math.max(1, s.tradeCount + 1)}`];
    }
    if (/ENTRY CHECK/.test(joined)) {
      return ['entry_check', 'ENTRY CHECK IN PROGRESS', 'Checking trading conditions'];
    }
    if (/AI AUTO ARMED|ANALYZ|SCANN|EVALUATING SAFE ENTRIES/.test(joined)) {
      return ['scanning', 'SCANNING DIGITS...', 'Reading live ticks and analysing digits'];
    }
    if (/READY|LOCKED/.test(joined) && s.targetDigit !== null) {
      return ['target_locked', `TARGET DIGIT IDENTIFIED: ${s.targetDigit}`, 'Digit selected and locked for monitoring'];
    }
    if (/MAX TRADES|STOP LIMIT|BOT STOPPED/.test(joined)) {
      return ['stopped', 'STOP LIMIT REACHED', `Cycle ended after ${s.tradeCount} trade(s)`];
    }
    return null;
  }

  function observeGuidedEvents() {
    if (!state.captureStartedAt) return;
    const s = snapshot();

    if (s.targetDigit !== null && s.targetDigit !== state.lastTargetDigit) {
      state.lastTargetDigit = s.targetDigit;
      addEvent(
        'target_selected',
        `TARGET DIGIT IDENTIFIED: ${s.targetDigit}`,
        'Digit selected and locked for monitoring',
        { targetDigit:s.targetDigit }
      );
    }

    if (s.tradeCount > state.lastTradeCount) {
      state.lastTradeCount = s.tradeCount;
      addEvent(
        'trade_bought',
        `TRADE ${s.tradeCount} EXECUTING`,
        `Target digit ${s.targetDigit ?? '-'} · watching the next tick`,
        { trade:s.tradeCount }
      );
    }

    if (s.activeContractId && s.activeContractId !== state.lastActiveContractId) {
      state.lastActiveContractId = s.activeContractId;
      if (s.tradeCount > 0) {
        addEvent(
          'contract_open',
          `TRADE ${s.tradeCount} EXECUTING`,
          `Contract open · target digit ${s.targetDigit ?? '-'}`,
          { trade:s.tradeCount, contractId:s.activeContractId }
        );
      }
    }

    const classified = classifyStatus(s);
    if (classified) addEvent(classified[0], classified[1], classified[2]);
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

    prepareCaptureView();

    try {
      status('Choose this tab + Share tab audio…', 'info');

      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          frameRate: { ideal:30, max:30 },
          width: { ideal:2560 },
          height: { ideal:1440 }
        },
        audio: {
          echoCancellation:false,
          noiseSuppression:false,
          autoGainControl:false
        },
        preferCurrentTab:true,
        selfBrowserSurface:'include',
        surfaceSwitching:'include',
        systemAudio:'include'
      });

      if (!stream.getAudioTracks().length) {
        stream.getTracks().forEach(t => t.stop());
        status('Enable Share tab audio and retry', 'bad');
        restoreCaptureView();
        alert(
          'DigitMatchStar Premium Capture needs tab audio.\n\n' +
          'Choose the DigitMatchStar tab and enable "Share tab audio".'
        );
        return;
      }

      state.displayStream = stream;
      stream.getVideoTracks()[0]?.addEventListener('ended', () => {
        if (state.recorder?.state === 'recording') {
          stopRecorderCleanly();
        }
        state.displayStream = null;
        restorePanel();
        restoreCaptureView();
      });

      // Allow the visual-only zoom/scroll position to settle.
      await new Promise(resolve => setTimeout(resolve, 450));
      startSessionRecorder();
    } catch (error) {
      console.warn('[DMS v5] capture permission failed:', error);
      status('Capture not enabled', 'bad');
      restoreCaptureView();
    }
  }

  function startSessionRecorder() {
    if (!state.displayStream) return;

    const options = {
      videoBitsPerSecond: 12_000_000,
      audioBitsPerSecond: 160_000
    };
    const mime = supportedMime();
    if (mime) options.mimeType = mime;

    state.chunks = [];
    state.captureStartedAt = Date.now();
    state.activeCycleId = null;
    state.lastCompletedCycle = null;
    state.lastSeenCurrent = !!currentCycle();
    state.events = [];
    state.stopPending = false;
    state.lastFingerprint = '';
    state.lastTradeCount = Number(window.tradeCount || 0);
    state.lastTargetDigit = null;
    state.lastActiveContractId = window.activeContract?.contractId ?? null;

    addEvent('capture_ready', 'TRADING SCREEN READY', 'Waiting for the next cycle');
    observeGuidedEvents();

    try {
      const recorder = new MediaRecorder(state.displayStream, options);
      state.recorder = recorder;
      recorder.ondataavailable = event => {
        if (event.data?.size) state.chunks.push(event.data);
      };
      recorder.onerror = event => console.warn('[DMS v5] recorder error:', event);
      recorder.onstop = finalizeRecording;

      hidePanelFromCapture();
      recorder.start(1000);

      console.log('🎥 DigitMatchStar v5 guided capture started. Trading logic untouched.');
    } catch (error) {
      restorePanel();
      restoreCaptureView();
      console.warn('[DMS v5] recorder start failed:', error);
      status('Recorder could not start', 'bad');
    }
  }

  function observeCycle() {
    observeGuidedEvents();

    const current = currentCycle();

    if (current && !state.lastSeenCurrent) {
      state.lastSeenCurrent = true;
      state.activeCycleId = cycleId(current);
      addEvent(
        'cycle_started',
        'SCANNING DIGITS...',
        'Cycle started · reading live market ticks'
      );
      return;
    }

    if (!current && state.lastSeenCurrent) {
      state.lastSeenCurrent = false;

      if (state.activeCycleId) {
        const completed = findCompletedCycle(state.activeCycleId);
        if (completed) {
          state.lastCompletedCycle = completed;
          const won = String(completed.status || '').toUpperCase() === 'WIN';
          const completedNet = Number(completed.netPnL ?? readBotPnl() ?? 0);
          const totalInvestment = Number(completed.totalInvestment ?? 0);
          const totalPayout = Number(completed.totalPayout ?? 0);
          const trades = Array.isArray(completed.trades) ? completed.trades : [];
          const winningTrade = trades.find(t => String(t.result || '').toUpperCase() === 'WIN') || trades[trades.length - 1] || {};
          const winningProfit = Number(winningTrade.profit ?? completed.winningProfit ?? 0);
          const lossesBeforeWin = Math.max(
            0,
            totalInvestment - Number(winningTrade.stake ?? winningTrade.buyPrice ?? 0)
          );

          addEvent(
            won ? 'cycle_win' : 'cycle_stopped',
            won ? (completedNet >= 0 ? 'LOSSES RECOVERED' : 'DIGIT MATCHED') : 'CYCLE COMPLETE',
            won
              ? (completedNet >= 0
                  ? `One winning trade recovered the earlier losses · cycle +$${completedNet.toFixed(2)}`
                  : `Winning trade +$${Math.max(0, winningProfit).toFixed(2)} · cycle P/L -$${Math.abs(completedNet).toFixed(2)}`)
              : `Cycle ended after ${trades.length} trade(s)`,
            {
              pnl: completedNet,
              cycleNetPnl: completedNet,
              totalInvestment,
              totalPayout,
              winningProfit,
              lossesBeforeWin,
              recoveredLosses: won && completedNet >= 0,
              tradeCount: trades.length
            }
          );
        }

        setTimeout(() => {
          if (state.recorder?.state === 'recording') {
            stopRecorderCleanly();
          }
        }, 3600);
      }
    }
  }


  function stopRecorderCleanly(delayMs = 180) {
    if (!state.recorder || state.recorder.state !== 'recording' || state.stopPending) return;
    state.stopPending = true;

    try {
      state.recorder.requestData();
    } catch (_) {}

    setTimeout(() => {
      try {
        if (state.recorder?.state === 'recording') {
          state.recorder.stop();
        }
      } catch (error) {
        console.warn('[DMS v5.6] clean stop failed:', error);
        state.stopPending = false;
      }
    }, delayMs);
  }

  async function blobLooksLikeWebM(blob) {
    if (!blob || blob.size < 32) return false;
    try {
      const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
      return head[0] === 0x1A &&
             head[1] === 0x45 &&
             head[2] === 0xDF &&
             head[3] === 0xA3;
    } catch (_) {
      return false;
    }
  }

  async function finalizeRecording() {
    state.stopPending = false;
    restorePanel();

    const mime = state.recorder?.mimeType || 'video/webm';
    const blob = new Blob(state.chunks, { type:mime });

    const validWebM = await blobLooksLikeWebM(blob);
    console.log('[DMS v5.6] capture finalized', {
      mime,
      bytes: blob.size,
      chunks: state.chunks.length,
      validWebM
    });

    if (!validWebM) {
      status('Capture invalid — not uploaded. Retry recording.', 'bad');
      console.error('[DMS v5.6] Invalid WebM capture; upload blocked.', {
        mime,
        bytes: blob.size,
        chunks: state.chunks.length
      });
      exposeDownload(blob);
      restoreCaptureView();
      return;
    }

    if (state.lastBlobUrl) {
      try { URL.revokeObjectURL(state.lastBlobUrl); } catch (_) {}
    }
    state.lastBlobUrl = URL.createObjectURL(blob);

    const completed = state.lastCompletedCycle || findCompletedCycle(state.activeCycleId);

    if (!completed) {
      status('Clip saved, but no completed cycle was found', 'bad');
      exposeDownload(blob);
      restoreCaptureView();
      return;
    }

    const payloadCycle = clone(completed) || {};
    payloadCycle.captureStartedAt = state.captureStartedAt;
    payloadCycle.captureHadAudio = true;
    payloadCycle.captureVersion = VERSION;
    payloadCycle.captureEvents = clone(state.events) || [];
    payloadCycle.captureViewport = {
      width: window.innerWidth,
      height: window.innerHeight,
      preparedZoom: 0.94
    };

    status('Building guided premium video…', 'info');

    try {
      await uploadForCompose(blob, payloadCycle);
      status('Sent to Telegram ✓', 'good');
    } catch (error) {
      console.error('[DMS v5] premium upload failed:', error);
      status(`Upload failed: ${error?.message || error}`, 'bad');
      exposeDownload(blob);
    } finally {
      restoreCaptureView();
    }
  }

  function exposeDownload(blob) {
    if (!state.panel) return;
    let a = document.getElementById('dms50-download');
    if (!a) {
      a = document.createElement('a');
      a.id = 'dms50-download';
      a.textContent = 'Download raw clip';
      a.style.cssText = [
        'display:block','margin-top:6px','padding:6px','border-radius:7px',
        'background:#1f2937','color:#fff','font-size:9px','font-weight:800',
        'text-align:center','text-decoration:none'
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
        method:'POST',
        headers:{
          'Content-Type':'application/json',
          'Authorization':`Bearer ${token}`
        },
        body:JSON.stringify({
          account_id:accountId,
          cycle_id:id,
          theme:'premium-guided-v5'
        })
      });

      const ticketData = await ticketResponse.json().catch(() => ({}));
      if (!ticketResponse.ok) {
        throw new Error(ticketData?.error || `Upload ticket failed (HTTP ${ticketResponse.status})`);
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
      } catch (_) {
        throw new Error('Cannot reach media worker.');
      }

      const result = await workerResponse.json().catch(() => ({}));
      if (!workerResponse.ok) {
        throw new Error(result?.detail || result?.error || `Media worker failed (HTTP ${workerResponse.status})`);
      }

      window.__dmsLastPremiumVideo = result;
      return result;
    } finally {
      state.uploading = false;
    }
  }

  function boot() {
    enforceSingleRecorderWindow();
    ensurePanel();
    state.observerTimer = setInterval(observeCycle, 150);
    console.log(
      `🎥 DigitMatchStar Premium Capture ${VERSION} loaded. ` +
      'Read-only event observer; trading functions untouched.'
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once:true });
  } else {
    boot();
  }

  window.dmsPremiumCapture = {
    version:VERSION,
    enable:enableCapture,
    getState:() => ({
      recording:state.recorder?.state === 'recording',
      captureStartedAt:state.captureStartedAt,
      activeCycleId:state.activeCycleId,
      eventCount:state.events.length,
      hasAudio:!!state.displayStream?.getAudioTracks?.().length,
      uploading:state.uploading
    }),
    getEvents:() => clone(state.events)
  };
})();
