(() => {
  "use strict";

  const SAFE_TICK_V1 = Object.freeze({
    name: "DigitMatchStar SAFE-TICK V1",
    version: "SAFE-TICK-V1-FROZEN-2026-10-04",
    symbol: "R_10",
    mode: "SHADOW_ONLY",
    candidateFreq25Max: 0.08,
    entropy10Max: 2.5219280948873625
  });

  function evaluate(entryFeatures) {
    if (!entryFeatures) {
      return { eligible: false, band: "INSUFFICIENT_DATA", shadowDecision: "NO_SCORE" };
    }

    const candidateFreq25 = Number(entryFeatures.candidateFreq25);
    const entropy10 = Number(entryFeatures.entropy10);

    if (!Number.isFinite(candidateFreq25) || !Number.isFinite(entropy10)) {
      return { eligible: false, band: "INSUFFICIENT_DATA", shadowDecision: "NO_SCORE" };
    }

    const eligible =
      candidateFreq25 <= SAFE_TICK_V1.candidateFreq25Max &&
      entropy10 <= SAFE_TICK_V1.entropy10Max;

    return {
      model: SAFE_TICK_V1.name,
      version: SAFE_TICK_V1.version,
      eligible,
      band: eligible ? "SAFE_TICK_V1" : "OUTSIDE_SAFE_ZONE",
      shadowDecision: eligible ? "ACCEPT_SHADOW" : "REJECT_SHADOW",
      inputs: { candidateFreq25, entropy10 },
      thresholds: {
        candidateFreq25Max: SAFE_TICK_V1.candidateFreq25Max,
        entropy10Max: SAFE_TICK_V1.entropy10Max
      },
      evaluatedAt: Date.now()
    };
  }

  function evaluateCandidate(candidate) {
    const result = evaluate(candidate && candidate.entryFeatures);
    return {
      cohortIndex: candidate?.cohortIndex ?? null,
      candidateDigit: candidate?.candidateDigit ?? null,
      ...result
    };
  }

  window.SafeTickV1 = Object.freeze({
    MODEL: SAFE_TICK_V1,
    evaluate,
    evaluateCandidate
  });

  console.info(
    "[SAFE-TICK V1] Frozen shadow selector loaded.",
    SAFE_TICK_V1.version
  );
})();