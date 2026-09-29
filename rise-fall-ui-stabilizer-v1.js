/* DigitMatchStar Rise/Fall UI Stabilizer v1.0
 * Presentation-only companion. Does not alter research, candidates, thresholds,
 * trading logic, cohort state, persistence, or execution.
 */
(() => {
  'use strict';

  const PANEL_ID = 'risefall-lab-v1-panel';
  const STYLE_ID = 'rf-ui-stabilizer-style-v1';
  let savedScrollTop = 0;
  let showCandidates = false;
  let lastDecorateAt = 0;

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${PANEL_ID}{
        width:370px!important;
        height:min(760px,78vh)!important;
        max-height:min(760px,78vh)!important;
        min-height:520px!important;
        overflow:hidden!important;
        contain:layout paint!important;
        transition:none!important;
        animation:none!important;
      }
      #${PANEL_ID}.minimized{
        width:248px!important;
        height:44px!important;
        min-height:44px!important;
        max-height:44px!important;
      }
      #${PANEL_ID} #rf-body{
        height:calc(min(760px,78vh) - 44px)!important;
        max-height:none!important;
        overflow-y:auto!important;
        overflow-x:hidden!important;
        scrollbar-gutter:stable!important;
        overscroll-behavior:contain!important;
        padding:9px!important;
      }
      #${PANEL_ID} .rf-panel{margin-bottom:7px!important;padding:8px!important}
      #${PANEL_ID} .rf-title{margin-bottom:5px!important}
      #${PANEL_ID} .rf-row{gap:5px!important}
      #${PANEL_ID} .rf-metric{padding:6px!important;min-height:44px}
      #${PANEL_ID} .rf-cand{margin:5px 0!important;padding:6px 7px!important}
      #${PANEL_ID} .rf-kpis{gap:3px!important}
      #${PANEL_ID} .rf-kpi{padding:4px!important}
      #${PANEL_ID} .rf-ui-hidden{display:none!important}
      #${PANEL_ID} .rf-ui-toolbar{
        display:flex;align-items:center;justify-content:space-between;gap:6px;
        margin:0 0 7px;padding:6px 7px;border:1px solid #20394f;border-radius:9px;
        background:#081522;position:sticky;top:0;z-index:3
      }
      #${PANEL_ID} .rf-ui-toolbar .rf-ui-status{
        font-size:10px;color:#8fb0ca;white-space:nowrap;overflow:hidden;text-overflow:ellipsis
      }
      #${PANEL_ID} .rf-ui-toggle{
        flex:0 0 auto;border:1px solid #33536b;background:#10283e;color:#e7f3fc;
        border-radius:7px;padding:5px 7px;font-size:10px;cursor:pointer
      }
      #${PANEL_ID} .rf-ui-toggle:hover{background:#153653}
      #${PANEL_ID} .rf-head{height:44px!important;transform:none!important;transition:none!important}
      @media(max-width:520px){
        #${PANEL_ID}{left:6px!important;right:6px!important;width:auto!important;height:74vh!important;max-height:74vh!important;min-height:460px!important}
        #${PANEL_ID} #rf-body{height:calc(74vh - 44px)!important}
        #${PANEL_ID}.minimized{left:6px!important;right:auto!important;width:248px!important;height:44px!important;min-height:44px!important}
      }
    `;
    document.head.appendChild(style);
  }

  function panelByTitle(body, title) {
    return [...body.querySelectorAll('.rf-panel')].find(p => {
      const t = p.querySelector('.rf-title');
      return t && t.textContent.trim().toLowerCase() === title.toLowerCase();
    }) || null;
  }

  function decorate() {
    const panel = document.getElementById(PANEL_ID);
    const body = document.getElementById('rf-body');
    if (!panel || !body) return;

    // The Rise/Fall lab rebuilds rf-body every tick. Restore the user's scroll position.
    body.scrollTop = Math.min(savedScrollTop, Math.max(0, body.scrollHeight - body.clientHeight));
    if (!body.dataset.rfStableScrollBound) {
      body.dataset.rfStableScrollBound = '1';
      body.addEventListener('scroll', () => { savedScrollTop = body.scrollTop; }, { passive: true });
    }

    // Keep the long candidate list collapsed in the live dashboard by default.
    const ranked = panelByTitle(body, 'Ranked frozen candidates');
    if (ranked) ranked.classList.toggle('rf-ui-hidden', !showCandidates);

    // Hide the long feature-family footer from the live view. It remains in JSON exports.
    for (const p of body.querySelectorAll('.rf-panel')) {
      const title = p.querySelector('.rf-title')?.textContent?.trim() || '';
      if (!title && /Feature family:/i.test(p.textContent || '')) p.classList.add('rf-ui-hidden');
    }

    if (!body.querySelector('.rf-ui-toolbar')) {
      const toolbar = document.createElement('div');
      toolbar.className = 'rf-ui-toolbar';
      toolbar.innerHTML = `
        <div class="rf-ui-status">Stable view · every tick is still scored</div>
        <button type="button" class="rf-ui-toggle">${showCandidates ? 'HIDE CANDIDATES' : 'SHOW CANDIDATES'}</button>
      `;
      const btn = toolbar.querySelector('button');
      btn.addEventListener('click', () => {
        showCandidates = !showCandidates;
        const r = panelByTitle(body, 'Ranked frozen candidates');
        if (r) r.classList.toggle('rf-ui-hidden', !showCandidates);
        btn.textContent = showCandidates ? 'HIDE CANDIDATES' : 'SHOW CANDIDATES';
      });
      body.prepend(toolbar);
    }
  }

  function start() {
    ensureStyle();
    const observer = new MutationObserver(() => {
      const now = performance.now();
      if (now - lastDecorateAt < 80) return;
      lastDecorateAt = now;
      requestAnimationFrame(decorate);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

    const timer = setInterval(() => {
      if (document.getElementById(PANEL_ID)) {
        decorate();
        clearInterval(timer);
      }
    }, 250);
    setTimeout(() => clearInterval(timer), 20000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
