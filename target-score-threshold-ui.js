/*
 * DigitMatchStar Target Score Gate V6
 * Display only. Execution enforcement is server-side in app/__init__.py.
 */
(() => {
    'use strict';

    const MIN_SCORE = 9.0;

    function ensureBadge() {
        const host = document.getElementById('recycle-runtime-panel');
        if (!host) return null;

        let el = document.getElementById('dms-score9-gate');
        if (el) return el;

        el = document.createElement('div');
        el.id = 'dms-score9-gate';
        el.className =
            'mb-3 rounded-lg border border-amber-500/30 bg-amber-950/20 p-2 text-[10px]';

        const ranking = document.getElementById('digit-score-ranking');
        if (ranking && ranking.parentElement === host) {
            host.insertBefore(el, ranking);
        } else {
            host.appendChild(el);
        }

        return el;
    }

    function render() {
        const st = window.SERVER_EXECUTION?.state || null;
        const score = st?.digit_score || null;
        const badge = ensureBadge();

        if (!badge || !score) return;

        const ranking = Array.isArray(score.ranking)
            ? [...score.ranking].sort(
                (a, b) => Number(b.score || 0) - Number(a.score || 0)
              )
            : [];

        const top = ranking[0] || null;
        const topDigit = Number(
            score.raw_selected_digit ?? top?.digit
        );
        const topScore = Number(
            score.raw_top_score ?? top?.score
        );

        const eligible =
            score.target_eligible === true ||
            (
                Number.isFinite(topScore) &&
                topScore >= Number(score.target_min_score ?? MIN_SCORE)
            );

        const threshold = Number(
            score.target_min_score ?? MIN_SCORE
        );

        badge.innerHTML = `
            <div class="flex items-center justify-between gap-3">
                <div>
                    <span class="text-amber-300 font-black">TARGET SCORE GATE</span>
                    <span class="text-slate-400"> · V1 #1 must be ≥ ${threshold.toFixed(2)}</span>
                </div>
                <div class="${
                    eligible ? 'text-emerald-300' : 'text-yellow-300'
                } font-black">
                    ${eligible ? 'ELIGIBLE ✓' : 'WAITING'}
                </div>
            </div>
            <div class="mt-1 text-slate-300">
                V1 #1:
                <b>${Number.isInteger(topDigit) ? topDigit : '—'}</b>
                · Score:
                <b>${Number.isFinite(topScore) ? topScore.toFixed(2) : '—'}</b>
                · Executable target:
                <b>${eligible && Number.isInteger(topDigit) ? topDigit : '—'}</b>
            </div>
        `;

        const next = document.getElementById('recycle-attempt');
        if (next && !eligible && !st?.open_contract_id) {
            next.textContent = '—';
        }

        const state = document.getElementById('score-engine-state');
        if (state && !eligible) {
            state.textContent =
                `WAITING FOR SCORE ≥ ${threshold.toFixed(2)} · ` +
                `V1 #1 ${Number.isInteger(topDigit) ? topDigit : '—'} ` +
                `(${Number.isFinite(topScore) ? topScore.toFixed(2) : '—'})`;
        }

        const note = document.getElementById('digit-score-note');
        if (note) {
            note.textContent =
                `Target Gate V6 · Only V1 rank #1 with score ≥ ${threshold.toFixed(2)} ` +
                `can become a new target. Scores below threshold wait for the next canonical tick.`;
        }
    }

    const timer = setInterval(render, 200);

    window.addEventListener(
        'beforeunload',
        () => clearInterval(timer)
    );

    if (document.readyState === 'loading') {
        document.addEventListener(
            'DOMContentLoaded',
            render,
            { once: true }
        );
    } else {
        render();
    }
})();
