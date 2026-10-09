/*
 * DigitMatchStar Contract Tick Timeline V4
 * Display only. It never places or changes a trade.
 */
(() => {
    'use strict';

    function ensurePanel() {
        let panel = document.getElementById('dms-contract-timeline-panel');
        if (panel) return panel;

        panel = document.createElement('section');
        panel.id = 'dms-contract-timeline-panel';
        panel.className =
            'mt-3 rounded-xl border border-cyan-500/30 bg-slate-950/80 p-3';

        panel.innerHTML = `
            <div class="flex items-center justify-between gap-2 mb-2">
                <div>
                    <div class="text-[10px] font-black uppercase tracking-wider text-cyan-300">
                        Contract Tick Timeline
                    </div>
                    <div class="text-[9px] text-slate-400">
                        Prediction tick → purchased target → eligible result tick
                    </div>
                </div>
                <div id="dms-timeline-verdict"
                     class="text-xs font-black text-yellow-300">WAITING</div>
            </div>

            <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
                <div class="rounded-lg border border-slate-700 p-2">
                    <div class="text-slate-500 uppercase">Prediction Source</div>
                    <div id="dms-timeline-origin" class="font-black text-white">—</div>
                </div>

                <div class="rounded-lg border border-slate-700 p-2">
                    <div class="text-slate-500 uppercase">Active Target</div>
                    <div id="dms-timeline-target" class="font-black text-cyan-300">—</div>
                </div>

                <div class="rounded-lg border border-slate-700 p-2">
                    <div class="text-slate-500 uppercase">Eligible Result Tick</div>
                    <div id="dms-timeline-result" class="font-black text-white">WAITING</div>
                </div>

                <div class="rounded-lg border border-slate-700 p-2">
                    <div class="text-slate-500 uppercase">Comparison</div>
                    <div id="dms-timeline-compare" class="font-black text-white">—</div>
                </div>
            </div>

            <div class="mt-2 text-[9px] leading-relaxed text-slate-400"
                 id="dms-timeline-detail">
                Waiting for an active server contract.
            </div>
        `;

        const ranking = document.getElementById('digit-score-ranking');

        if (ranking && ranking.parentElement) {
            ranking.parentElement.appendChild(panel);
        } else {
            const tradeStatus = document.getElementById('trade-result-container');

            if (tradeStatus && tradeStatus.parentElement) {
                tradeStatus.parentElement.appendChild(panel);
            } else {
                document.body.appendChild(panel);
            }
        }

        return panel;
    }

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function render() {
        ensurePanel();

        const st = window.SERVER_EXECUTION?.state || null;
        const settlement = st?.last_settlement || null;
        const t = settlement?.trade_timeline || null;

        if (!t) {
            setText('dms-timeline-verdict', 'WAITING');
            setText('dms-timeline-origin', '—');
            setText('dms-timeline-target', '—');
            setText('dms-timeline-result', 'WAITING');
            setText('dms-timeline-compare', '—');
            setText(
                'dms-timeline-detail',
                'No active contract timeline has been published by the server yet.'
            );
            return;
        }

        const target = Number(t.target_digit);
        const resultDigit = Number(t.result_digit);
        const originDigit = Number(t.prediction_origin_digit);

        const targetKnown = Number.isInteger(target);
        const resultKnown = Number.isInteger(resultDigit);

        const fast = String(t.fast_result || 'WAITING').toUpperCase();

        const official = t.official_contract_match === true
            ? String(t.official_result || '').toUpperCase()
            : '';

        setText(
            'dms-timeline-origin',
            `e:${t.prediction_origin_epoch ?? '—'} · digit ${
                Number.isInteger(originDigit) ? originDigit : '—'
            }`
        );

        setText(
            'dms-timeline-target',
            targetKnown ? String(target) : '—'
        );

        setText(
            'dms-timeline-result',
            resultKnown
                ? `e:${t.result_epoch ?? '—'} · digit ${resultDigit}`
                : 'WAITING FOR NEXT ELIGIBLE TICK'
        );

        setText(
            'dms-timeline-compare',
            resultKnown && targetKnown
                ? (
                    target === resultDigit
                        ? `${target} = ${resultDigit}`
                        : `${target} ≠ ${resultDigit}`
                )
                : '—'
        );

        const verdict = document.getElementById('dms-timeline-verdict');

        if (verdict) {
            verdict.textContent = official
                ? `${fast} · DERIV ${official}`
                : fast;

            verdict.className =
                'text-xs font-black ' +
                (
                    fast === 'WIN'
                        ? 'text-emerald-300'
                        : fast === 'LOSS'
                            ? 'text-rose-300'
                            : 'text-yellow-300'
                );
        }

        const detail = [
            `Contract ${t.contract_id || '—'} · Trade ${t.trade_no || '—'}`,
            `Armed after epoch ${t.armed_after_epoch ?? '—'}`,
            resultKnown
                ? 'The result digit above is the first eligible SERVER tick after the contract was armed.'
                : 'The visible market digit is not counted until its epoch is later than the armed epoch.'
        ];

        if (official) {
            detail.push(
                `Official Deriv result: ${official}` +
                (
                    Number.isFinite(Number(t.official_profit))
                        ? ` · P/L ${Number(t.official_profit).toFixed(2)}`
                        : ''
                )
            );
        }

        setText(
            'dms-timeline-detail',
            detail.join(' · ')
        );
    }

    const timer = setInterval(render, 250);

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
