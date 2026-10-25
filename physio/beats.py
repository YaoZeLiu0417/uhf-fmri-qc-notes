"""Offline PPG event comparison against scanner pulse markers and an alternate detector.

The historical function name ``causal_detect`` is retained for compatibility.
Its optional whole-record percentile cap (used by evaluate_ppg) is noncausal.
Batch indices do not establish streaming performance or acquisition-to-output
latency. Marker-relative offsets are not ECG R-peak error or MHD robustness.
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
    """Return offline decision indices; clip_pct requires the entire recording."""
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or not np.isfinite(x).all() or not np.isfinite(fs) or fs <= 0:
        raise ValueError("Expected finite one-dimensional samples and positive fs")
    if adapt_s <= 0 or refractory_s < 0 or smooth_s < 0:
        raise ValueError("Invalid detector time constants")
    if not x.size:
        return np.array([], dtype=int)
    det, last = [], -np.inf
    n_adapt = max(1, int(adapt_s * fs)); run_max = 0.0
    w = max(1, int(smooth_s * fs)); c = np.cumsum(np.insert(x, 0, 0.0))
    # A trailing mean at original sample i must retain exactly the original length.
    # The legacy concatenation produced N+1 samples and shifted the filtered path.
    ends = np.arange(1, len(x) + 1)
    starts = np.maximum(0, ends - w)
    x = (c[ends] - c[starts]) / (ends - starts)
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
    """Greedy one-to-one marker agreement in [ref - tol, ref + max_lag].

The broad historical window is retained; report it alongside all metrics.
Legacy latency/jitter keys remain aliases, not validated latency measures.
"""
    if not np.isfinite(fs) or fs <= 0 or tol_s < 0 or max_lag_s < 0:
        raise ValueError("Invalid sampling rate or matching window")
    ref_t, det_t = np.asarray(ref_idx) / fs, np.asarray(det_idx) / fs
    for events in (ref_t, det_t):
        if events.ndim != 1 or not np.isfinite(events).all() or np.any(events < 0) or np.any(np.diff(events) <= 0):
            raise ValueError("Events must be finite, nonnegative and strictly increasing")
    used = np.zeros(len(det_t), bool); lat = []; tp = 0
    for r in ref_t:
        j = np.searchsorted(det_t, r - tol_s)
        while j < len(det_t) and det_t[j] <= r + max_lag_s:
            if not used[j]:
                used[j] = True; tp += 1; lat.append(det_t[j] - r); break
            j += 1
    lat = np.asarray(lat) * 1000
    out = {"n_ref": int(len(ref_t)), "n_det": int(len(det_t)), "n_matched": tp,
           "n_unmatched_reference": int(len(ref_t)-tp), "n_unmatched_detection": int(len(det_t)-tp),
           "matching_window_seconds": [-tol_s, max_lag_s],
           "sensitivity": tp / len(ref_t) if len(ref_t) else None,
           "ppv": tp / len(det_t) if len(det_t) else None}
    if lat.size:
        med = float(np.median(lat))
        out.update({"latency_ms_median": med, "latency_ms_p95": float(np.percentile(lat, 95)),
                    "jitter_ms_sd": float(lat.std()), "jitter_ms_iqr": float(np.subtract(*np.percentile(lat, [75, 25]))),
                    "outliers_pct_beyond_100ms": float(100 * np.mean(np.abs(lat - med) > 100))})
        out.update({"offset_ms_median": out["latency_ms_median"],
                    "offset_ms_p95": out["latency_ms_p95"],
                    "timing_sd_ms": out["jitter_ms_sd"], "timing_iqr_ms": out["jitter_ms_iqr"]})
    return out

def evaluate_ppg(signal, fs, scanner_trigger_idx=None):
    """Offline comparison. Returns (results dict, held signal, detections, reference)."""
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
