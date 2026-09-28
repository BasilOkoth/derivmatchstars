/*
 * DigitMatchStar Tail Risk Model V1.1
 * ADMIN-ONLY + MINIMIZABLE + SHADOW-ONLY RESEARCH
 *
 * IMPORTANT:
 * - Does not place, block, stop, size, retry, or alter trades.
 * - Uses the same /api/capture-access authorization pattern as TailGuard.
 * - Completely invisible/inactive for unauthorized users.
 */

(() => {
  'use strict';

  const VERSION = 'TAIL-RISK-V1.6-DOCKABLE-MIN';
  const STORE_KEY = 'digitmatchstar_tail_risk_model_v11';
  const MIN_KEY = 'matchstar_panel_min_tail-risk-model';
  const POLL_MS = 500;
  const ADMIN_RECHECK_MS = 60000;
  const CHECKPOINTS = [3, 5, 7];

  let adminAuthorized = null;
  let adminCheckInFlight = false;
  let adminLastCheckedAt = 0;

  let panel = null;
  let body = null;
  let minimizeBtn = null;
  let statusEl = null;
  let detailEl = null;

  function globalBinding(name) {
    try {
      return (0, eval)(`typeof ${name} !== 'undefined' ? ${name} : null`);
    } catch (_) {
      return null;
    }
  }

  async function checkAdminAccess(force = false) {
    const now = Date.now();

    if (!force && adminAuthorized !== null && (now - adminLastCheckedAt) < ADMIN_RECHECK_MS) {
      return adminAuthorized;
    }
    if (adminCheckInFlight) return adminAuthorized === true;

    adminCheckInFlight = true;

    try {
      const accountId =
        localStorage.getItem('active_account') ||
        localStorage.getItem('derivAccount') ||
        localStorage.getItem('derivDemoAccount') ||
        localStorage.getItem('derivRealAccount') ||
        '';

      const token =
        localStorage.getItem('active_token') ||
        localStorage.getItem('derivToken') ||
        localStorage.getItem('derivTokenDemo') ||
        localStorage.getItem('derivTokenReal') ||
        '';

      if (!token || !accountId) {
        adminAuthorized = false;
        adminLastCheckedAt = now;
        return false;
      }

      const response = await fetch('/api/capture-access', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        credentials: 'same-origin',
        body: JSON.stringify({ account_id: accountId })
      });

      if (!response.ok) {
        adminAuthorized = false;
        adminLastCheckedAt = now;
        return false;
      }

      const data = await response.json().catch(() => ({}));

      adminAuthorized = !!(
        data.allowed === true ||
        data.authorized === true ||
        data.captureAllowed === true ||
        data.captureAdmin === true ||
        data.ok === true
      );

      adminLastCheckedAt = now;
      return adminAuthorized;
    } catch (_) {
      adminAuthorized = false;
      adminLastCheckedAt = now;
      return false;
    } finally {
      adminCheckInFlight = false;
    }
  }

  function hideCompletely() {
    if (panel && document.body.contains(panel)) panel.remove();
    panel = null;
    body = null;
    minimizeBtn = null;
    statusEl = null;
    detailEl = null;
  }

  function isMinimized() {
    try {
      const saved = localStorage.getItem(MIN_KEY);
      return saved === null ? true : saved === '1';
    } catch (_) {
      return true;
    }
  }

  function saveMinimized(v) {
    try {
      localStorage.setItem(MIN_KEY, v ? '1' : '0');
    } catch (_) {}
  }

  function setMinimized(minimized) {
    const next = !!minimized;
    saveMinimized(next);

    if (body) {
      body.style.display = next ? 'none' : 'block';
    }

    if (minimizeBtn) {
      minimizeBtn.textContent = next ? '+' : '−';
      minimizeBtn.title = next ? 'Expand Tail Risk Model' : 'Minimize Tail Risk Model';
      minimizeBtn.setAttribute('aria-expanded', next ? 'false' : 'true');
      minimizeBtn.setAttribute(
        'aria-label',
        next ? 'Expand Tail Risk Model' : 'Minimize Tail Risk Model'
      );
    }

    if (panel) {
      panel.dataset.minimized = next ? '1' : '0';
      panel.style.width = next ? '260px' : 'min(360px,calc(100vw - 28px))';
    }
  }


  function makePanelDraggable(target, handle) {
    if (!target || !handle || target.dataset.dmsDraggable === '1') return;

    const POS_KEY = 'matchstar_tail_risk_panel_position';

    // Restore prior position when available.
    try {
      const saved = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
      if (
        saved &&
        Number.isFinite(saved.left) &&
        Number.isFinite(saved.top)
      ) {
        target.style.right = 'auto';
        target.style.bottom = 'auto';
        target.style.left = `${Math.max(0, saved.left)}px`;
        target.style.top = `${Math.max(0, saved.top)}px`;
      }
    } catch (_) {}

    let dragging = false;
    let moved = false;
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let startTop = 0;

    handle.style.cursor = 'move';
    handle.style.touchAction = 'none';
    handle.style.userSelect = 'none';

    handle.addEventListener('pointerdown', event => {
      if (event.button !== undefined && event.button !== 0) return;

      // Buttons remain clickable; dragging starts only on free header space.
      if (event.target.closest('button')) return;

      const rect = target.getBoundingClientRect();

      dragging = true;
      moved = false;
      startX = event.clientX;
      startY = event.clientY;
      startLeft = rect.left;
      startTop = rect.top;

      target.style.right = 'auto';
      target.style.bottom = 'auto';
      target.style.left = `${rect.left}px`;
      target.style.top = `${rect.top}px`;

      try { handle.setPointerCapture(event.pointerId); } catch (_) {}
      event.preventDefault();
    });

    handle.addEventListener('pointermove', event => {
      if (!dragging) return;

      const dx = event.clientX - startX;
      const dy = event.clientY - startY;

      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) moved = true;

      const maxLeft = Math.max(0, window.innerWidth - target.offsetWidth);
      const maxTop = Math.max(0, window.innerHeight - target.offsetHeight);

      const nextLeft = Math.min(maxLeft, Math.max(0, startLeft + dx));
      const nextTop = Math.min(maxTop, Math.max(0, startTop + dy));

      target.style.left = `${nextLeft}px`;
      target.style.top = `${nextTop}px`;
    });

    const endDrag = event => {
      if (!dragging) return;
      dragging = false;

      try { handle.releasePointerCapture(event.pointerId); } catch (_) {}

      if (moved) {
        const rect = target.getBoundingClientRect();
        try {
          localStorage.setItem(
            POS_KEY,
            JSON.stringify({
              left: Math.round(rect.left),
              top: Math.round(rect.top)
            })
          );
        } catch (_) {}
      }
    };

    handle.addEventListener('pointerup', endDrag);
    handle.addEventListener('pointercancel', endDrag);

    target.dataset.dmsDraggable = '1';
  }

  function ensurePanel() {
    if (adminAuthorized !== true) {
      hideCompletely();
      return;
    }

    if (panel && document.body.contains(panel)) return;

    panel = document.createElement('section');
    panel.id = 'tail-risk-model-panel';
    panel.style.cssText = [
      'position:fixed',
      'right:18px',
      'bottom:18px',
      'z-index:99999',
      'width:min(360px,calc(100vw - 28px))',
      'background:rgba(5,15,11,.96)',
      'border:1px solid rgba(34,197,94,.28)',
      'border-radius:18px',
      'box-shadow:0 22px 60px rgba(0,0,0,.42)',
      'backdrop-filter:blur(16px)',
      'color:#ecfdf5',
      'font-family:Inter,system-ui,sans-serif',
      'overflow:hidden'
    ].join(';');

    const header = document.createElement('div');
    header.id = 'tail-risk-model-drag-handle';
    header.style.cssText = [
      'display:flex',
      'align-items:center',
      'justify-content:space-between',
      'gap:10px',
      'padding:12px 14px',
      'border-bottom:1px solid rgba(255,255,255,.08)',
      'background:rgba(34,197,94,.06)'
    ].join(';');

    const titleWrap = document.createElement('div');
    titleWrap.innerHTML = `
      <div style="font-weight:800;font-size:13px;letter-spacing:.02em">Tail Risk Model</div>
      <div style="font-size:10px;color:#86efac;margin-top:2px">ADMIN · SHADOW RESEARCH · DRAG HERE</div>
    `;

    minimizeBtn = document.createElement('button');
    minimizeBtn.type = 'button';
    minimizeBtn.setAttribute('aria-label', 'Minimize Tail Risk Model');
    minimizeBtn.style.cssText = [
      'width:30px',
      'height:28px',
      'border-radius:999px',
      'border:1px solid rgba(255,255,255,.12)',
      'background:rgba(255,255,255,.06)',
      'color:#fff',
      'font-size:18px',
      'line-height:1',
      'cursor:pointer'
    ].join(';');
    minimizeBtn.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      const currentlyMinimized =
        panel?.dataset?.minimized === '1' ||
        body?.style?.display === 'none';
      setMinimized(!currentlyMinimized);
    });

    header.appendChild(titleWrap);
    header.appendChild(minimizeBtn);

    body = document.createElement('div');
    body.style.cssText = 'padding:14px';

    statusEl = document.createElement('div');
    statusEl.style.cssText = 'font-size:13px;font-weight:700;color:#38bdf8;margin-bottom:8px';
    statusEl.textContent = 'Initializing research model…';

    detailEl = document.createElement('div');
    detailEl.style.cssText = 'font-size:12px;line-height:1.65;color:#cbd5e1';

    body.appendChild(statusEl);
    body.appendChild(detailEl);

    panel.appendChild(header);
    panel.appendChild(body);
    document.body.appendChild(panel);

    makePanelDraggable(panel, header);
    setMinimized(isMinimized());
  }

  function loadStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {};
      return {
        version: VERSION,
        createdAt: parsed.createdAt || new Date().toISOString(),
        records: Array.isArray(parsed.records) ? parsed.records : [],
        forward: Array.isArray(parsed.forward) ? parsed.forward : []
      };
    } catch (_) {
      return { version: VERSION, createdAt: new Date().toISOString(), records: [], forward: [] };
    }
  }

  function saveStore(store) {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(store));
    } catch (_) {}
  }

  function getCyclePerformance() {
    return globalBinding('cyclePerformance') || window.cyclePerformance || null;
  }

  function currentSymbol() {
    return document.getElementById('symbol')?.value || window.tickFormat?.symbol || 'UNKNOWN';
  }

  function history() {
    const cp = getCyclePerformance();
    if (!cp) return [];
    const symbol = currentSymbol();

    try {
      if (typeof cp.load === 'function') {
        const rows = cp.load(symbol);
        if (Array.isArray(rows)) return rows;
      }
    } catch (_) {}

    if (cp.historyBySymbol && Array.isArray(cp.historyBySymbol[symbol])) {
      return cp.historyBySymbol[symbol];
    }

    return [];
  }

  function snapshots(cycle) {
    return Array.isArray(cycle?.tailTrajectory) ? cycle.tailTrajectory : [];
  }

  function snapshotAt(cycle, tradeNumber) {
    const traj = snapshots(cycle);
    if (!traj.length) return null;

    const exact = traj.filter(
      s => Number(s?.tradeNumber) === tradeNumber && s?.trigger !== 'MATCH_DETECTED'
    );

    if (exact.length) {
      return exact.find(s => s?.trigger === 'LOSS_AFTER_TICK') ||
             exact.find(s => s?.trigger === 'PURCHASE') ||
             exact[exact.length - 1];
    }

    const prior = traj.filter(
      s => Number(s?.tradeNumber) <= tradeNumber && s?.trigger !== 'MATCH_DETECTED'
    );
    return prior.length ? prior[prior.length - 1] : null;
  }

  function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function featureVector(s) {
    if (!s) return null;
    return {
      gapP90: num(s.gapP90),
      extendRatio: num(s.extendRatio),
      targetFreq20: num(s.targetFreq20),
      targetFreq50: num(s.targetFreq50),
      targetFreq100: num(s.targetFreq100),
      nextTickProbability: num(s.nextTickProbability),
      p5: num(s.p5),
      p10: num(s.p10),
      s20: num(s.s20),
      aiScore: num(s.aiScore),
      entropy: num(s.entropy),
      chi2: num(s.chi2),
      dominance: num(s.dominance),
      consecutiveExtendingGaps: num(s.consecutiveExtendingGaps)
    };
  }

  function sigmoid(x) {
    return 1 / (1 + Math.exp(-Math.max(-20, Math.min(20, x))));
  }

  function predictRisk(f, cp) {
    if (!f) return null;

    let z = -0.35;

    if (Number.isFinite(f.gapP90)) z += 1.35 * (f.gapP90 - 0.65);
    if (Number.isFinite(f.extendRatio)) z += 0.85 * (f.extendRatio - 1.20);
    if (Number.isFinite(f.targetFreq20)) z += -2.0 * (f.targetFreq20 - 0.10);
    if (Number.isFinite(f.targetFreq50)) z += -1.2 * (f.targetFreq50 - 0.10);
    if (Number.isFinite(f.targetFreq100)) z += -0.7 * (f.targetFreq100 - 0.10);
    if (Number.isFinite(f.nextTickProbability)) z += -0.35 * (f.nextTickProbability - 0.10);
    if (Number.isFinite(f.s20)) z += 0.5 * f.s20;
    if (Number.isFinite(f.consecutiveExtendingGaps)) z += 0.08 * Math.max(0, f.consecutiveExtendingGaps - 1);

    if (cp === 5) z += 0.10;
    if (cp === 7) z += 0.20;

    return sigmoid(z);
  }

  function riskLabel(p) {
    if (!Number.isFinite(p)) return 'UNKNOWN';
    if (p >= 0.80) return 'VERY HIGH';
    if (p >= 0.65) return 'HIGH';
    if (p >= 0.45) return 'MODERATE';
    return 'LOW';
  }

  function resolvedBeyond10(cycle) {
    if (!cycle) return null;
    if (cycle.status === 'STOPPED') return 1;

    const w = Number(cycle.winningTradeNumber);
    if (cycle.status === 'WIN' && Number.isFinite(w)) return w > 10 ? 1 : 0;

    return null;
  }

  function upsertPredictions() {
    const store = loadStore();
    const cp = getCyclePerformance();

    const completedRows = history();
    const currentCycle = cp?.current || cp?.currentCycle || null;

    // Process current cycle first so live T3/T5/T7 readings appear immediately.
    const rows = [];
    if (currentCycle?.id) rows.push(currentCycle);
    for (const row of completedRows) {
      if (!row?.id) continue;
      if (currentCycle?.id && String(row.id) === String(currentCycle.id)) continue;
      rows.push(row);
    }

    for (const cycle of rows) {
      if (!cycle?.id) continue;

      const id = String(cycle.id);
      let rec = store.records.find(r => r.id === id);

      if (!rec) {
        rec = {
          id,
          symbol: cycle.symbol || currentSymbol(),
          createdAt: new Date().toISOString(),
          checkpoints: {},
          outcome: null
        };
        store.records.push(rec);
      }

      // Update symbol if it becomes available later.
      if (!rec.symbol || rec.symbol === 'UNKNOWN') {
        rec.symbol = cycle.symbol || currentSymbol();
      }

      const traj = snapshots(cycle);

      for (const checkpoint of CHECKPOINTS) {
        const key = String(checkpoint);

        // Predictions are immutable once frozen.
        if (rec.checkpoints[key]?.frozen === true) continue;

        // IMPORTANT: a checkpoint is reached only when an exact LOSS_AFTER_TICK
        // snapshot exists for that trade. This prevents purchase/endpoint leakage.
        const exactLossSnapshot = traj.find(
          s =>
            Number(s?.tradeNumber) === checkpoint &&
            s?.trigger === 'LOSS_AFTER_TICK'
        );

        if (!exactLossSnapshot) continue;

        const features = featureVector(exactLossSnapshot);
        const probability = predictRisk(features, checkpoint);

        rec.checkpoints[key] = {
          frozen: true,
          frozenAt: new Date().toISOString(),
          checkpoint,
          snapshotTrigger: 'LOSS_AFTER_TICK',
          probability,
          label: riskLabel(probability),
          features
        };
      }

      // Only score outcome once the cycle is actually resolved.
      const outcome = resolvedBeyond10(cycle);

      if (outcome !== null && rec.outcome === null) {
        rec.outcome = {
          tailBeyond10: outcome,
          resolvedAt: new Date().toISOString(),
          status: cycle.status || null,
          winningTradeNumber: num(cycle.winningTradeNumber)
        };

        for (const checkpoint of CHECKPOINTS) {
          const pred = rec.checkpoints[String(checkpoint)];
          if (!pred?.frozen || !Number.isFinite(pred.probability)) continue;

          const already = store.forward.some(
            x => x.id === id && Number(x.checkpoint) === checkpoint
          );

          if (!already) {
            store.forward.push({
              id,
              symbol: rec.symbol,
              checkpoint,
              probability: pred.probability,
              predictedLabel: pred.label,
              actual: outcome,
              scoredAt: new Date().toISOString()
            });
          }
        }
      }
    }

    if (store.records.length > 3000) store.records = store.records.slice(-3000);
    if (store.forward.length > 6000) store.forward = store.forward.slice(-6000);

    saveStore(store);
    return store;
  }

  function mean(xs) {
    const ys = xs.filter(Number.isFinite);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
  }

  function brier(rows) {
    if (!rows.length) return null;
    return rows.reduce((a, r) => a + Math.pow(r.probability - r.actual, 2), 0) / rows.length;
  }

  function auc(rows) {
    const pos = rows.filter(r => r.actual === 1);
    const neg = rows.filter(r => r.actual === 0);
    if (!pos.length || !neg.length) return null;

    let score = 0;
    for (const p of pos) {
      for (const n of neg) {
        if (p.probability > n.probability) score += 1;
        else if (p.probability === n.probability) score += 0.5;
      }
    }
    return score / (pos.length * neg.length);
  }


  function currentCycleRecord(store) {
    const cp = getCyclePerformance();
    const current = cp?.current || cp?.currentCycle || null;
    if (!current?.id) return null;
    return store.records.find(r => String(r.id) === String(current.id)) || null;
  }

  function checkpointDisplay(rec, cp) {
    const row = rec?.checkpoints?.[String(cp)];
    if (!row?.frozen || !Number.isFinite(row.probability)) {
      return {
        text: 'PENDING',
        tone: '#94a3b8',
        detail: `Waiting for Trade ${cp}`
      };
    }

    const pct = (row.probability * 100).toFixed(1) + '%';
    const label = row.label || 'UNKNOWN';
    let tone = '#22c55e';
    if (label === 'MODERATE') tone = '#f59e0b';
    if (label === 'HIGH') tone = '#fb7185';
    if (label === 'VERY HIGH') tone = '#ef4444';

    return {
      text: `${pct} · ${label}`,
      tone,
      detail: `Frozen at Trade ${cp}`
    };
  }

  function render(store) {
    if (adminAuthorized !== true) {
      hideCompletely();
      return;
    }

    ensurePanel();
    if (!statusEl || !detailEl) return;

    const forward = store.forward || [];
    const rec = currentCycleRecord(store);

    statusEl.textContent = rec
      ? 'Current cycle tail-risk monitoring'
      : 'Forward tail-risk research active';

    const currentRows = CHECKPOINTS.map(cp => {
      const d = checkpointDisplay(rec, cp);
      return `
        <div style="
          display:grid;
          grid-template-columns:46px 1fr;
          gap:10px;
          align-items:center;
          padding:8px 0;
          border-bottom:1px solid rgba(255,255,255,.06)
        ">
          <div style="font-weight:900;font-size:13px;color:#e2e8f0">T${cp}</div>
          <div>
            <div style="font-weight:900;color:${d.tone};font-size:13px">${d.text}</div>
            <div style="font-size:10px;color:#64748b;margin-top:2px">${d.detail}</div>
          </div>
        </div>
      `;
    }).join('');

    const statsHtml = CHECKPOINTS.map(cp => {
      const rows = forward.filter(r => Number(r.checkpoint) === cp);
      const n = rows.length;
      const actualRate = mean(rows.map(r => r.actual));
      const meanP = mean(rows.map(r => r.probability));
      const bs = brier(rows);
      const a = auc(rows);

      return `
        <div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.06)">
          <b>T${cp} forward:</b> N=${n}<br>
          Actual tail rate: <b>${Number.isFinite(actualRate) ? (actualRate*100).toFixed(1)+'%' : '—'}</b><br>
          Mean predicted: <b>${Number.isFinite(meanP) ? (meanP*100).toFixed(1)+'%' : '—'}</b><br>
          Brier: <b>${Number.isFinite(bs) ? bs.toFixed(3) : '—'}</b><br>
          AUC: <b>${Number.isFinite(a) ? a.toFixed(3) : '—'}</b>
        </div>
      `;
    }).join('');

    detailEl.innerHTML = `
      <div style="
        margin-bottom:12px;
        padding:10px 11px;
        border-radius:10px;
        background:rgba(15,23,42,.55);
        border:1px solid rgba(148,163,184,.14)
      ">
        <div style="font-size:11px;font-weight:900;color:#7dd3fc;margin-bottom:4px">
          CURRENT CYCLE
        </div>
        <div style="font-size:10px;color:#64748b;margin-bottom:4px">
          ${rec?.id ? `Cycle ${String(rec.id).slice(-8)}` : 'No active cycle'}
        </div>
        ${currentRows}
      </div>

      <details open style="
        border-top:1px solid rgba(255,255,255,.08);
        padding-top:8px
      ">
        <summary style="
          cursor:pointer;
          font-size:11px;
          font-weight:900;
          color:#86efac;
          user-select:none
        ">
          FORWARD VALIDATION HISTORY
        </summary>
        <div style="margin-top:8px">
          ${statsHtml}
        </div>
      </details>

      <div style="color:#64748b;font-size:10px;margin-top:10px">
        Admin only · shadow research · never controls live trades
      </div>
    `;
  }

  async function tick() {
    if (!document.body) return;

    const authorized = await checkAdminAccess(false);

    if (!authorized) {
      hideCompletely();
      return;
    }

    const store = upsertPredictions();
    render(store);
  }

  window.DMSTailRiskModel = {
    version: VERSION,
    async authorized() { return checkAdminAccess(true); },
    minimize() { setMinimized(true); },
    expand() { setMinimized(false); },
    getStore() { return loadStore(); },
    getResearchSnapshot() {
      const store = loadStore();
      const checkpointSummary = {};

      for (const cp of CHECKPOINTS) {
        const rows = (store.forward || []).filter(r => Number(r.checkpoint) === cp);
        const actualRate = mean(rows.map(r => r.actual));
        const meanPredicted = mean(rows.map(r => r.probability));
        checkpointSummary[`T${cp}`] = {
          n: rows.length,
          actualTailRate: actualRate,
          meanPredictedRisk: meanPredicted,
          brierScore: brier(rows),
          rocAuc: auc(rows)
        };
      }

      return {
        schema: 'DIGITMATCHSTAR_TAIL_RISK_RESEARCH_V1',
        generatedAt: new Date().toISOString(),
        version: VERSION,
        researchOnly: true,
        target: 'P(TARGET_SURVIVES_BEYOND_TRADE_10)',
        checkpoints: checkpointSummary,
        records: store.records,
        forwardValidation: store.forward
      };
    },
    exportJSON() { return JSON.stringify(loadStore(), null, 2); }
  };

  (async () => {
    const authorized = await checkAdminAccess(true);

    if (!authorized) {
      hideCompletely();
      return;
    }

    ensurePanel();
    setInterval(() => { tick().catch(() => {}); }, POLL_MS);
    setTimeout(() => { tick().catch(() => {}); }, 500);
  })();
})();
