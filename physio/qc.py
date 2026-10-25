"""Recording-level physiological QC and derived phase/RVT estimates.

These estimates are not a complete, acquisition-sampled RETROICOR design.
Flat signals and missing metadata identify measurement limitations, not causes.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks
from .siemens_pmu import PMURecording, is_flatline
from .beats import offline_detect


def clipped_pct(x, lo=0, hi=4095) -> float | None:
    x = np.asarray(x)
    return float(100 * np.mean((x <= lo) | (x >= hi))) if x.size else None


def longest_constant_run_s(x, fs) -> float:
    if not len(x):
        return 0.0
    ch = np.flatnonzero(np.diff(x) != 0)
    runs = np.diff(np.concatenate([[-1], ch, [len(x) - 1]]))
    return float(runs.max() / fs)


def _signal_issue(x, fs, padlen, minimum_fs):
    if not np.isfinite(fs) or fs <= minimum_fs:
        return "sampling rate unsupported by detector filter"
    if not len(x):
        return "empty signal"
    if not np.all(np.isfinite(x)):
        return "non-finite signal samples"
    if is_flatline(x):
        return "flat line / insufficient variation; cause undetermined"
    if len(x) <= padlen:
        return "recording too short for detector filter"
    return None


def breaths_from_bellows(x, fs, band=(0.05, 1.0), min_period_s=1.5):
    x = np.asarray(x, float)
    if _signal_issue(x, fs, 15, 2 * band[1]):
        return np.array([], dtype=int), np.array([], dtype=int), np.full(x.shape, np.nan)
    sos = butter(2, list(band), btype="band", fs=fs, output="sos")
    y = sosfiltfilt(sos, x)
    pk, _ = find_peaks(y, distance=max(1, int(min_period_s * fs)), prominence=np.std(y) * 0.5)
    tr, _ = find_peaks(-y, distance=max(1, int(min_period_s * fs)), prominence=np.std(y) * 0.5)
    return pk, tr, y


def rate_series(events_idx, fs, win_s=60, step_s=10, total_s=None):
    t = np.asarray(events_idx) / fs
    if total_s is None:
        total_s = t[-1] if t.size else 0.0
    centres = np.arange(win_s / 2, total_s - win_s / 2, step_s)
    if len(t) < 2:
        return centres, np.full(centres.shape, np.nan)
    return centres, np.array([60 * np.sum((t >= c - win_s / 2) & (t < c + win_s / 2)) / win_s for c in centres])


def cardiac_phase(n, beats):
    """Recording-level pulse phase between detected PPG events, not ECG phase."""
    ph = np.full(n, np.nan)
    beats = np.asarray(beats, dtype=int)
    beats = np.unique(beats[(beats >= 0) & (beats < n)])
    for a, b in zip(beats[:-1], beats[1:]):
        ph[a:b] = 2 * np.pi * (np.arange(a, b) - a) / (b - a)
    return ph


def respiratory_phase(y, bins=100):
    y = np.asarray(y, float)
    if len(y) < 2 or not np.all(np.isfinite(y)) or np.ptp(y) == 0:
        return np.full(y.shape, np.nan)
    hist, edges = np.histogram(y, bins=bins)
    cdf = np.cumsum(hist) / hist.sum()
    idx = np.clip(np.digitize(y, edges) - 1, 0, bins - 1)
    return np.pi * cdf[idx] * np.sign(np.gradient(y))


def rvt(y, pk, tr, fs, t_out):
    """Uncalibrated recording-level RVT; no extrapolation outside event support."""
    y, pk, tr, t_out = np.asarray(y), np.asarray(pk, dtype=int), np.asarray(tr, dtype=int), np.asarray(t_out)
    if len(pk) < 2 or len(tr) < 2:
        return np.full(t_out.shape, np.nan)
    tp, ttr = pk / fs, tr / fs
    env_hi = np.interp(t_out, tp, y[pk], left=np.nan, right=np.nan)
    env_lo = np.interp(t_out, ttr, y[tr], left=np.nan, right=np.nan)
    period = np.interp(t_out, tp[1:], np.diff(tp), left=np.nan, right=np.nan)
    return np.divide(env_hi - env_lo, period, out=np.full(t_out.shape, np.nan), where=period > 0)


def _recording_report(rec):
    x = rec.signal
    return {"file": Path(rec.path).name, "kind": rec.kind, "fs": rec.fs,
            "sampling_rate_source": getattr(rec, "fs_source", "unspecified"),
            "parser_warnings": getattr(rec, "warnings", []),
            "duration_min": round(rec.duration_s / 60, 2),
            "footer_present": bool(rec.footer), "footer_duration_s": rec.footer_duration_s(),
            "clock_endpoints_present": all(k in rec.footer for k in ("LogStartMDHTime", "LogStopMDHTime")),
            "flatline": is_flatline(x), "clipped_pct": clipped_pct(x),
            "longest_constant_run_s": round(longest_constant_run_s(x, rec.fs), 3),
            "scanner_physiological_markers": int(len(rec.trigger_idx)),
            "interpretation": "Recording-level descriptive QC; detected events and derived phase are not independently validated."}


def qc_puls(rec: PMURecording) -> tuple[dict, np.ndarray | None]:
    rep = _recording_report(rec)
    rep.update({"kind": "puls", "beats_detected": 0, "pulse_rate_bpm_median": None,
                "pulse_rate_bpm_p5_p95": None, "pulse_interval_outliers_pct": None})
    issue = _signal_issue(rec.signal, rec.fs, 21, 16)
    if issue:
        rep["verdict"] = "FAIL: " + issue
        return rep, None
    bt, _ = offline_detect(rec.signal, rec.fs)
    rep["beats_detected"] = int(len(bt))
    if len(bt) < 2:
        rep["verdict"] = "FAIL: fewer than two detected PPG pulses; rate unavailable"
        return rep, None
    ibi = np.diff(bt) / rec.fs
    rep.update({"pulse_rate_bpm_median": round(60 / np.median(ibi), 1),
                "pulse_rate_bpm_p5_p95": [round(v, 1) for v in 60 / np.percentile(ibi, [95, 5])],
                "pulse_interval_outliers_pct": round(100 * np.mean((ibi < 0.4) | (ibi > 1.6)), 2)})
    flags = []
    if rep["clipped_pct"] > 1: flags.append("PPG clipping — inspect gain and clip placement")
    if rep["longest_constant_run_s"] > 5: flags.append(f"constant segment {rep['longest_constant_run_s']:.1f} s")
    if not rep["clock_endpoints_present"]: flags.append("missing MDH clock endpoints; effective clock alignment unverified")
    if not (40 <= rep["pulse_rate_bpm_median"] <= 120): flags.append("pulse-rate estimate outside QC range")
    rep["verdict"] = "OK" if not flags else "WARN: " + "; ".join(flags)
    return rep, bt


def qc_resp(rec: PMURecording) -> tuple[dict, tuple]:
    rep = _recording_report(rec)
    rep.update({"kind": "resp", "breaths_detected": 0, "rr_per_min_median": None,
                "rr_per_min_p5_p95": None, "cushion_gain_changes": int(sum("Gain" in m for m in rec.messages))})
    issue = _signal_issue(rec.signal, rec.fs, 15, 2)
    pk, tr, y = breaths_from_bellows(rec.signal, rec.fs)
    if issue:
        rep["verdict"] = "FAIL: " + issue
        return rep, (pk, tr, y)
    rep["breaths_detected"] = int(len(pk))
    if len(pk) < 2 or len(tr) < 2:
        rep["verdict"] = "FAIL: insufficient respiratory peaks/troughs; rate and RVT unavailable"
        return rep, (pk, tr, y)
    bp = np.diff(pk) / rec.fs
    rep.update({"rr_per_min_median": round(60 / np.median(bp), 1),
                "rr_per_min_p5_p95": [round(v, 1) for v in 60 / np.percentile(bp, [95, 5])]})
    flags = []
    if not rep["clock_endpoints_present"]: flags.append("missing MDH clock endpoints; effective clock alignment unverified")
    if rep["clipped_pct"] > 1: flags.append("bellows clipping")
    if rep["longest_constant_run_s"] > 5: flags.append(f"constant segment {rep['longest_constant_run_s']:.1f} s")
    if not (6 <= rep["rr_per_min_median"] <= 30): flags.append("breathing-rate estimate outside QC range")
    rep["verdict"] = "OK" if not flags else "WARN: " + "; ".join(flags)
    return rep, (pk, tr, y)


def alignment(puls: PMURecording, resp: PMURecording) -> dict | None:
    """MDH start-clock offset, assuming a common day; not independent TTL validation."""
    fp, fr = puls.footer, resp.footer
    if "LogStartMDHTime" not in fp or "LogStartMDHTime" not in fr:
        return None
    def hms(ms):
        return None if ms is None else f"{ms//3600000:02d}:{ms%3600000//60000:02d}:{ms%60000/1000:06.3f}"
    return {"resp_start_minus_puls_start_s": (fr["LogStartMDHTime"] - fp["LogStartMDHTime"]) / 1000.0,
            "puls_MDH_start": hms(fp["LogStartMDHTime"]), "puls_MDH_stop": hms(fp.get("LogStopMDHTime")),
            "resp_MDH_start": hms(fr["LogStartMDHTime"]), "resp_MDH_stop": hms(fr.get("LogStopMDHTime")),
            "note": "Clock-assumed same-day alignment: t_resp = t_puls - (resp_start - puls_start). No independent TTL, drift or date-rollover validation."}
