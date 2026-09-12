"""Beat detection on pulse-oximeter (PPG) signals: a causal streaming detector, an offline reference detector,
and a scorer that reports what a closed-loop paradigm actually needs — sensitivity, PPV, latency and jitter.

Design notes
- Causal path: sample-and-hold across ADC clipping -> trailing moving average -> causal slope -> adaptive threshold
  from a leaky running maximum -> refractory period. Only past samples are used, so the decision index is the
  earliest sample at which a real-time system could have acted.
- Slope-based detection is insensitive to slow additive components (e.g. the MHD-elevated T wave that ruins ECG
  amplitude thresholds at ultra-high field); see scripts/sim_ecg_mhd.py for the negative illustration.
- Jitter is reported as SD *and* IQR: a handful of mis-pairings at high heart rate inflates the SD while the IQR
  stays at ~10 ms. Report the IQR and the outlier fraction together.
"""
from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks

def causal_hold_clipped(x: np.ndarray, clip_hi: int = 4095, clip_lo: int = 0):
    """Sample-and-hold across ADC saturation (12-bit PMU channel clips at 0/4095). Causal."""
    y = x.astype(float).copy(); bad = (x >= clip_hi) | (x <= clip_lo)
    for i in range(1, len(y)):
        if bad[i]: y[i] = y[i - 1]
    return y, int(bad.sum())

def causal_detect(x, fs, refractory_s=0.35, adapt_s=3.0, k=0.45, slope_win=3, clip_pct=None, smooth_s=0.02):
    """Streaming detector. Returns sample indices at which a beat decision is emitted."""
    det, last = [], -np.inf
    n_adapt = int(adapt_s * fs); run_max = 0.0
    w = max(1, int(smooth_s * fs)); c = np.cumsum(np.insert(x, 0, 0.0))
    x = np.concatenate([x[:w], (c[w:] - c[:-w]) / w]) if w > 1 else x       # trailing mean (past samples only)
    slope_win = max(slope_win, w)
    d = np.zeros_like(x); d[slope_win:] = x[slope_win:] - x[:-slope_win]     # causal slope
    if clip_pct is not None:
        d = np.clip(d, None, np.percentile(d, clip_pct))                     # guard against residual spikes (PPG)
    for i in range(1, len(x)):
        run_max = max(run_max * (1 - 1 / n_adapt), d[i])                     # leaky running max
        if d[i - 1] > k * run_max and d[i] <= d[i - 1] and (i - last) / fs > refractory_s:
            det.append(i); last = i
    return np.asarray(det, dtype=int)

def offline_detect(x, fs, band=(0.5, 8.0), min_ibi_s=0.4, prom_sd=0.8):
    """Non-causal reference: zero-phase band-pass + peak picking with physiological spacing."""
    sos = butter(3, list(band), btype="band", fs=fs, output="sos")
    y = sosfiltfilt(sos, np.asarray(x, float))
    pk, _ = find_peaks(y, distance=int(min_ibi_s * fs), prominence=np.std(y) * prom_sd)
    return pk, y

def score(ref_idx, det_idx, fs, tol_s=0.3, max_lag_s=0.6):
    """Match each reference beat to the first unused detection in [ref - tol, ref + max_lag]."""
    ref_t, det_t = np.asarray(ref_idx) / fs, np.asarray(det_idx) / fs
    used = np.zeros(len(det_t), bool); lat = []; tp = 0
    for r in ref_t:
        j = np.searchsorted(det_t, r - tol_s)
        while j < len(det_t) and det_t[j] <= r + max_lag_s:
            if not used[j]:
                used[j] = True; tp += 1; lat.append(det_t[j] - r); break
            j += 1
    lat = np.asarray(lat) * 1000
    out = {"n_ref": int(len(ref_t)), "n_det": int(len(det_t)),
           "sensitivity": tp / max(len(ref_t), 1), "ppv": tp / max(len(det_t), 1)}
    if lat.size:
        med = float(np.median(lat))
        out.update({"latency_ms_median": med, "latency_ms_p95": float(np.percentile(lat, 95)),
                    "jitter_ms_sd": float(lat.std()), "jitter_ms_iqr": float(np.subtract(*np.percentile(lat, [75, 25]))),
                    "outliers_pct_beyond_100ms": float(100 * np.mean(np.abs(lat - med) > 100))})
    return out

def evaluate_ppg(signal, fs, scanner_trigger_idx=None):
    """Full evaluation of the causal detector on one PPG recording. Returns (results dict, held signal, det, ref)."""
    x, n_clip = causal_hold_clipped(np.asarray(signal))
    det = causal_detect(x, fs, clip_pct=99.5)
    off, _ = offline_detect(x, fs)
    res = {"fs": fs, "duration_min": round(len(x) / fs / 60, 2), "clipped_samples": n_clip,
           "clipped_pct": round(100 * n_clip / len(x), 2), "vs_offline_detector": score(off, det, fs)}
    if scanner_trigger_idx is not None and len(scanner_trigger_idx):
        res["vs_scanner_triggers"] = score(scanner_trigger_idx, det, fs)
        res["scanner_triggers_vs_offline"] = score(off, scanner_trigger_idx, fs)
        ref = np.asarray(scanner_trigger_idx)
    else:
        ref = off
    return res, x, det, ref
