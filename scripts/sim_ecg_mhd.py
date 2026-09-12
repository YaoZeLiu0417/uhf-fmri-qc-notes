"""Negative illustration: why amplitude-based ECG triggering degrades in the magnet and why a slope detector does not.
Simulates ECG with an MHD-like elevated T wave (amplitude --mhd, relative to R = 1) and scores the causal detector.

  python scripts/sim_ecg_mhd.py --mhd 0.9 --out results/sim/ecg_mhd_0.9
"""
import argparse, json, os, sys, numpy as np
from _common import ROOT
from physio.beats import causal_detect, score
from physio.plots import plot_beats

def simulate_ecg(fs, duration, hr, mhd_amp, rng):
    t = np.arange(0, duration, 1 / fs); rr = 60 / hr
    beats = np.cumsum(rng.normal(rr, 0.04 * rr, int(duration / rr) + 5)); beats = beats[beats < duration]
    ecg = np.zeros_like(t)
    for b in beats:
        ecg += np.exp(-((t - b) ** 2) / (2 * 0.008 ** 2)) + 0.25 * np.exp(-((t - b - 0.25) ** 2) / (2 * 0.04 ** 2))
        ecg += mhd_amp * np.exp(-((t - b - 0.22) ** 2) / (2 * 0.05 ** 2))   # MHD-like elevated T wave
    ecg += 0.05 * rng.normal(size=t.size) + 0.1 * np.sin(2 * np.pi * 0.25 * t)
    return ecg, beats

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--fs", type=int, default=1000); ap.add_argument("--duration", type=float, default=120)
    ap.add_argument("--hr", type=float, default=65); ap.add_argument("--mhd", type=float, default=0.6); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "sim", "ecg_mhd")); a = ap.parse_args()
    x, beats = simulate_ecg(a.fs, a.duration, a.hr, a.mhd, np.random.default_rng(a.seed))
    det = causal_detect(x, a.fs, k=0.55)
    b = np.round(beats * a.fs).astype(int)
    res = {"mode": "sim", "mhd_amp": a.mhd, "vs_true_beats": score(b, det, a.fs, tol_s=0.05, max_lag_s=0.1)}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    plot_beats(x, a.fs, b, det, a.out, f"simulated ECG, MHD amplitude {a.mhd}")
    json.dump(res, open(a.out + ".json", "w"), indent=2); print(json.dumps(res, indent=2))
