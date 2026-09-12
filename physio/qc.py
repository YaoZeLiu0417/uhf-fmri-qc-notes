"""Physiological-log QC and nuisance regressors.

Checks an operator should run before leaving the console:
  flat-line (sensor never connected) · ADC clipping (gain too high) · dropouts (long constant runs) ·
  rate sanity and drift · footer present (log stopped cleanly; MDH clock enables alignment to DICOM AcquisitionTime)
Regressors: RETROICOR cardiac/respiratory phases (Glover, Li & Ress 2000) and RVT (Birn et al. 2006).
"""
from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks
from .siemens_pmu import PMURecording, is_flatline
from .beats import offline_detect

# ------------------------------------------------------------------ signal-level checks
def clipped_pct(x, lo=0, hi=4095) -> float:
    return float(100 * np.mean((x <= lo) | (x >= hi)))

def longest_constant_run_s(x, fs) -> float:
    ch = np.flatnonzero(np.diff(x) != 0)
    if len(ch) == 0: return len(x) / fs
    runs = np.diff(np.concatenate([[-1], ch, [len(x) - 1]]))
    return float(runs.max() / fs)

def breaths_from_bellows(x, fs, band=(0.05, 1.0), min_period_s=1.5):
    sos = butter(2, list(band), btype="band", fs=fs, output="sos")
    y = sosfiltfilt(sos, np.asarray(x, float))
    pk, _ = find_peaks(y, distance=int(min_period_s * fs), prominence=np.std(y) * 0.5)
    tr, _ = find_peaks(-y, distance=int(min_period_s * fs), prominence=np.std(y) * 0.5)
    return pk, tr, y

def rate_series(events_idx, fs, win_s=60, step_s=10, total_s=None):
    t = np.asarray(events_idx) / fs; total_s = total_s or t[-1]
    centres = np.arange(win_s / 2, total_s - win_s / 2, step_s)
    return centres, np.array([60 * np.sum((t >= c - win_s / 2) & (t < c + win_s / 2)) / win_s for c in centres])

# ------------------------------------------------------------------ regressors
def cardiac_phase(n, beats):
    ph = np.full(n, np.nan)
    for a, b in zip(beats[:-1], beats[1:]):
        ph[a:b] = 2 * np.pi * (np.arange(a, b) - a) / (b - a)
    return ph

def respiratory_phase(y, bins=100):
    ymin, ymax = np.nanmin(y), np.nanmax(y)
    hist, edges = np.histogram(y, bins=bins, range=(ymin, ymax)); cdf = np.cumsum(hist) / hist.sum()
    idx = np.clip(np.digitize(y, edges) - 1, 0, bins - 1)
    return np.pi * cdf[idx] * np.sign(np.gradient(y))

def rvt(y, pk, tr, fs, t_out):
    tp, ttr = pk / fs, tr / fs
    env_hi = np.interp(t_out, tp, y[pk]); env_lo = np.interp(t_out, ttr, y[tr])
    period = np.interp(t_out, tp[1:], np.diff(tp))
    return (env_hi - env_lo) / period

# ------------------------------------------------------------------ per-file QC
def qc_puls(rec: PMURecording) -> dict:
    x = rec.signal
    rep = {"file": rec.path.split("/")[-1], "kind": "puls", "fs": rec.fs, "duration_min": round(rec.duration_s / 60, 2),
           "footer_present": bool(rec.footer), "footer_duration_s": rec.footer_duration_s(), "flatline": is_flatline(x),
           "clipped_pct": round(clipped_pct(x), 2), "longest_constant_run_s": round(longest_constant_run_s(x, rec.fs), 3),
           "scanner_triggers": int(len(rec.trigger_idx))}
    flags = []
    if rep["flatline"]:
        rep["verdict"] = "FAIL: flat line — sensor not connected"; return rep, None
    bt, _ = offline_detect(x, rec.fs); ibi = np.diff(bt) / rec.fs
    rep.update({"beats_detected": int(len(bt)), "hr_bpm_median": round(60 / np.median(ibi), 1),
                "hr_bpm_p5_p95": [round(v, 1) for v in 60 / np.percentile(ibi, [95, 5])],
                "ibi_outliers_pct": round(100 * np.mean((ibi < 0.4) | (ibi > 1.6)), 2),
                "scanner_missed_beats_pct": round(100 * (1 - len(rec.trigger_idx) / len(bt)), 1) if len(rec.trigger_idx) else None})
    if rep["clipped_pct"] > 1: flags.append("PPG clipping — lower gain / reposition finger clip")
    if rep["longest_constant_run_s"] > 5: flags.append(f"dropout {rep['longest_constant_run_s']:.1f} s")
    if not rep["footer_present"]: flags.append("no footer — log not stopped cleanly")
    if not (40 <= rep["hr_bpm_median"] <= 120): flags.append("implausible heart rate")
    rep["verdict"] = "OK" if not flags else "WARN: " + "; ".join(flags)
    return rep, bt

def qc_resp(rec: PMURecording) -> dict:
    x = rec.signal
    pk, tr, y = breaths_from_bellows(x, rec.fs); bp = np.diff(pk) / rec.fs
    rep = {"file": rec.path.split("/")[-1], "kind": "resp", "fs": rec.fs, "duration_min": round(rec.duration_s / 60, 2),
           "footer_present": bool(rec.footer), "flatline": is_flatline(x), "clipped_pct": round(clipped_pct(x), 2),
           "longest_constant_run_s": round(longest_constant_run_s(x, rec.fs), 3), "scanner_triggers": int(len(rec.trigger_idx)),
           "breaths_detected": int(len(pk)), "rr_per_min_median": round(60 / np.median(bp), 1),
           "rr_per_min_p5_p95": [round(v, 1) for v in 60 / np.percentile(bp, [95, 5])],
           "cushion_gain_changes": int(sum("Gain" in m for m in rec.messages))}
    flags = []
    if rep["flatline"]: rep["verdict"] = "FAIL: flat line"; return rep, (pk, tr, y)
    if not rep["footer_present"]: flags.append("no footer — log not stopped cleanly, MDH alignment impossible")
    if rep["clipped_pct"] > 1: flags.append("bellows clipping")
    if not (6 <= rep["rr_per_min_median"] <= 30): flags.append("implausible breathing rate")
    rep["verdict"] = "OK" if not flags else "WARN: " + "; ".join(flags)
    return rep, (pk, tr, y)

def alignment(puls: PMURecording, resp: PMURecording) -> dict | None:
    """Offset between the two logs from the MDH wall clock (ms since midnight). None if a footer is missing."""
    fp, fr = puls.footer, resp.footer
    if "LogStartMDHTime" not in fp or "LogStartMDHTime" not in fr: return None
    def hms(ms): return f"{ms//3600000:02d}:{ms%3600000//60000:02d}:{ms%60000/1000:06.3f}"
    return {"resp_start_minus_puls_start_s": round((fr["LogStartMDHTime"] - fp["LogStartMDHTime"]) / 1000.0, 3),
            "puls_MDH_start": hms(fp["LogStartMDHTime"]), "puls_MDH_stop": hms(fp["LogStopMDHTime"]),
            "resp_MDH_start": hms(fr["LogStartMDHTime"]), "resp_MDH_stop": hms(fr["LogStopMDHTime"]),
            "note": "DICOM AcquisitionTime uses the same wall clock; shift resp by the offset to put it on the puls clock"}
