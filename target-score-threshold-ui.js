/*
 * DigitMatchStar Target Score Gate V9
 * Display-only synchronization fix.
 */
(() => {
    'use strict';

    const DEFAULT_MIN_SCORE = 9.0;

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

    function currentRankState(score) {
        const ranking = Array.isArray(score?.ranking)
            ? [...score.ranking].sort(
                (a, b) => Number(b?.score ?? -Infinity) - Number(a?.score ?? -Infinity)
              )
            : [];

        const top = ranking[0] || null;

        const topDigit =
            top && Number.isInteger(Number(top.digit))
                ? Number(top.digit)
                : null;

        const topScore =
            top && Number.isFinite(Number(top.score))
                ? Number(top.score)
                : null;

        const threshold =
            Number.isFinite(Number(score?.target_min_score))
                ? Number(score.target_min_score)
                : DEFAULT_MIN_SCORE;

        const eligible = Boolean(
            score?.ready &&
            topDigit !== null &&
            topScore !== null &&
            topScore >= threshold
        );

        return { topDigit, topScore, threshold, eligible };
    }

    function render() {
        const st = window.SERVER_EXECUTION?.state || null;
        const score = st?.digit_score || null;
        const badge = ensureBadge();

        if (!badge) return;

        if (!score) {
            badge.innerHTML = `
                <div class="flex items-center justify-between gap-3">
                    <div>
                        <span class="text-amber-300 font-black">TARGET SCORE GATE</span>
                        <span class="text-slate-400"> · waiting for server ranking</span>
                    </div>
                    <div class="text-yellow-300 font-black">WAITING</div>
                </div>
            `;
            return;
        }

        const { topDigit, topScore, threshold, eligible } = currentRankState(score);

        const openTarget = Number(st?.open_contract_target);
        const hasOpenTarget = Number.isInteger(openTarget);

        badge.innerHTML = `
            <div class="flex items-center justify-between gap-3">
                <div>
                    <span class="text-amber-300 font-black">TARGET SCORE GATE</span>
                    <span class="text-slate-400"> · V1 #1 must be ≥ ${threshold.toFixed(2)}</span>
                </div>
                <div class="${eligible ? 'text-emerald-300' : 'text-yellow-300'} font-black">
                    ${eligible ? 'ELIGIBLE ✓' : 'WAITING'}
                </div>
            </div>

            <div class="mt-1 text-slate-300">
                V1 #1:
                <b>${topDigit !== null ? topDigit : '—'}</b>
                · Score:
                <b>${topScore !== null ? topScore.toFixed(2) : '—'}</b>
                · Executable target:
                <b>${eligible && topDigit !== null ? topDigit : '—'}</b>
            </div>

            ${
                hasOpenTarget
                    ? `<div class="mt-1 text-cyan-300">
                           Open contract target: <b>${openTarget}</b>
                       </div>`
                    : ''
            }
        `;

        const next = document.getElementById('recycle-attempt');
        if (next && !hasOpenTarget) {
            next.textContent =
                eligible && topDigit !== null
                    ? String(topDigit)
                    : '—';
        }

        const state = document.getElementById('score-engine-state');
        if (state) {
            const margin = Number(score?.top_margin);
            const marginText = Number.isFinite(margin)
                ? ` · V1 margin ${margin.toFixed(3)}`
                : '';

            if (eligible) {
                state.textContent =
                    `V1 #1 ${topDigit} · score ${topScore.toFixed(2)} · ELIGIBLE${marginText}`;
            } else {
                state.textContent =
                    `WAITING FOR SCORE ≥ ${threshold.toFixed(2)} · ` +
                    `V1 #1 ${topDigit !== null ? topDigit : '—'} ` +
                    `(${topScore !== null ? topScore.toFixed(2) : '—'})${marginText}`;
            }
        }

        const note = document.getElementById('digit-score-note');
        if (note) {
            note.textContent =
                `Target Gate V9 · Eligibility now uses the exact same current ` +
                `ranking array as DIGIT SCORE 0–9. Only V1 rank #1 with score ` +
                `≥ ${threshold.toFixed(2)} can become a new target.`;
        }
    }

    const timer = setInterval(render, 150);

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
