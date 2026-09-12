"""Regression tests. Two layers:
1. Synthetic tests (always run): parser round-trip and detector on a synthetic PPG.
2. Real-data tests (skipped if data absent): every session in sessions.json must keep its expected QC verdict class,
   and the dev sessions must keep sensitivity >= 0.99 / PPV >= 0.98 against scanner triggers.
Run:  python -m pytest tests -q
"""
import os, sys, json, numpy as np, pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
from physio import load_pmu, is_flatline, evaluate_ppg, qc_puls, qc_resp
from physio.beats import causal_detect, score
from _common import load_sessions

def synthetic_ppg(fs=400, dur=60, hr=70, seed=0):
    rng = np.random.default_rng(seed); t = np.arange(0, dur, 1 / fs)
    beats = np.cumsum(rng.normal(60 / hr, 0.03, int(dur * hr / 60) + 3)); beats = beats[beats < dur]
    x = np.zeros_like(t)
    for b in beats: x += np.exp(-((t - b - 0.15) ** 2) / (2 * 0.06 ** 2))
    return (2048 + 800 * x + 10 * rng.normal(size=t.size)).astype(int), beats

def test_causal_detector_on_synthetic_ppg():
    x, beats = synthetic_ppg(); det = causal_detect(x.astype(float), 400, clip_pct=99.5)
    det, beats = det[det > 5 * 400], beats[beats > 5]          # skip the adaptive threshold's warm-up (first 5 s)
    s = score(np.round(beats * 400).astype(int), det, 400, tol_s=0.05, max_lag_s=0.3)
    assert s["sensitivity"] > 0.98 and s["ppv"] > 0.98

def test_flatline_detector():
    assert is_flatline(np.full(4000, 2048)); assert not is_flatline(synthetic_ppg()[0])

SESS = load_sessions()
have_data = all(os.path.exists(p) for s in SESS.values() for k, p in s.items() if k in ("puls", "resp"))
real = pytest.mark.skipif(not have_data, reason="raw PMU logs not available (set PHYSIO_DATA_ROOT)")

@real
@pytest.mark.parametrize("name", list(SESS))
def test_qc_verdict_class_is_stable(name):
    s = SESS[name]
    vp = qc_puls(load_pmu(s["puls"]))[0]["verdict"].split(":")[0]
    vr = qc_resp(load_pmu(s["resp"]))[0]["verdict"].split(":")[0]
    assert vp == s["expect"]["puls"], f"{name} puls verdict changed to {vp}"
    assert vr == s["expect"]["resp"], f"{name} resp verdict changed to {vr}"

@real
@pytest.mark.parametrize("name", [k for k, v in SESS.items() if v["role"] == "dev"])
def test_dev_sessions_keep_detector_performance(name):
    rec = load_pmu(SESS[name]["puls"]); res, *_ = evaluate_ppg(rec.signal, rec.fs, rec.trigger_idx)
    v = res["vs_scanner_triggers"]
    assert v["sensitivity"] >= 0.99 and v["ppv"] >= 0.98 and v["jitter_ms_iqr"] <= 20
