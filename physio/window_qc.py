"""Fixed descriptive checks in 30-second, half-open run windows.

Sample membership is [onset, end), including a final partial window. Exact
constant sequences are found across the run before assigning them to windows.
Their duration is (N - 1) / fs, not N / fs. Artifact categories can overlap;
their support durations must not be added without taking their union.
"""
from __future__ import annotations

import numpy as np


def _true_runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return edges.reshape(-1, 2)


def window_qc(samples, fs, start_time, run_duration):
    """Return windows, raw artifact intervals, coverage, and explicit rules.

    ``start_time`` is the first raw sample's seconds relative to run onset.
    Indices refer to the original array. ``clip_fraction`` is a finite-sample
    fraction; coverage/support seconds are separate from sample counts.
    ``no_rule_flag`` never means physiologically validated or accepted.
    """
    x = np.asarray(samples)
    if x.ndim != 1 or not np.issubdtype(x.dtype, np.number) or np.iscomplexobj(x):
        raise ValueError("samples must be a one-dimensional real numeric array")
    if any(isinstance(v, (bool, np.bool_)) or not np.isfinite(v) for v in (fs, start_time, run_duration)):
        raise ValueError("fs, start_time and run_duration must be finite numbers")
    fs, start_time, run_duration = float(fs), float(start_time), float(run_duration)
    if fs <= 0 or run_duration <= 0:
        raise ValueError("fs and run_duration must be positive")

    times = start_time + np.arange(len(x), dtype=float) / fs
    low, high = np.searchsorted(times, [0.0, run_duration], side="left")
    values, run_times = x[low:high], times[low:high]
    finite = np.isfinite(values)
    adc = finite & ((values <= 0) | (values >= 4095))
    out_of_range = finite & ((values < 0) | (values > 4095))
    if len(times):
        coverage_start = min(run_duration, max(0.0, float(times[0])))
        coverage_stop = max(coverage_start, min(run_duration, max(0.0, float(times[-1]))))
    else:
        coverage_start = coverage_stop = 0.0

    if len(values):
        changes = np.flatnonzero(values[1:] != values[:-1]) + 1
        starts, stops = np.r_[0, changes], np.r_[changes, len(values)]
        keep = (stops - starts > 1) & finite[starts]
        starts, stops = starts[keep], stops[keep]
    else:
        starts = stops = np.array([], dtype=int)
    spans = (stops - starts - 1) / fs
    long_constant = spans > 5.0

    artifacts = []
    groups = [("adc_boundary", _true_runs(adc)),
              ("long_constant", np.column_stack([starts[long_constant], stops[long_constant]])),
              ("nonfinite", _true_runs(~finite)),
              ("out_of_range", _true_runs(out_of_range))]
    for kind, bounds in groups:
        for a, b in bounds:
            onset = float(run_times[a])
            span = float((b - a - 1) / fs)
            end = float(run_times[b - 1])
            support_stop = min(run_duration, coverage_stop, end + 1 / fs)
            interval = {
                "kind": kind, "onset_s": onset, "end_s": end,
                "duration_s": span, "support_duration_s": max(0.0, support_stop - onset),
                "support_stop_s": support_stop,
                "sample_start": int(low + a), "sample_stop": int(low + b),
                "n_samples": int(b - a),
            }
            if kind == "long_constant":
                interval["constant_span_s"] = span
            artifacts.append(interval)
    artifacts.sort(key=lambda row: (row["onset_s"], row["kind"]))

    windows = []
    for index, onset in enumerate(np.arange(0.0, run_duration, 30.0)):
        end = min(float(onset) + 30.0, run_duration)
        a, b = np.searchsorted(run_times, [onset, end], side="left")
        n = int(b - a)
        n_finite = int(finite[a:b].sum())
        n_unique = int(np.unique(values[a:b][finite[a:b]]).size)
        clip_count = int(adc[a:b].sum())
        clip_fraction = clip_count / n_finite if n_finite else None
        nonfinite_count = n - n_finite
        outside_count = int(out_of_range[a:b].sum())
        touched = (starts < b) & (stops > a)
        longest = float(spans[touched].max()) if np.any(touched) else 0.0
        covered = max(0.0, min(end, coverage_stop) - max(float(onset), coverage_start))
        duration = end - float(onset)
        reasons = []
        if not n:
            reasons.append("no_samples")
        elif not n_finite:
            reasons.append("no_finite_samples")
        elif n_unique == 1:
            reasons.append("flat_line")
        elif n_unique < 5:
            reasons.append("fewer_than_5_unique_values")
        unusable = bool(reasons)
        if covered < duration - 1e-9:
            reasons.append("incomplete_coverage")
        if clip_fraction is not None and clip_fraction > 0.01:
            reasons.append("adc_boundary_fraction_gt_0.01")
        if longest > 5.0:
            reasons.append("long_constant_span_gt_5s")
        if nonfinite_count:
            reasons.append("nonfinite_samples")
        if outside_count:
            reasons.append("out_of_range_samples")
        windows.append({
            "window_index": index, "onset_s": float(onset), "duration_s": duration,
            "sample_start": int(low + a), "sample_stop": int(low + b),
            "n_samples": n, "finite_sample_count": n_finite, "finite_unique_count": n_unique,
            "clip_count": clip_count, "clip_fraction": clip_fraction,
            "longest_constant_span_s": longest,
            "nonfinite_count": nonfinite_count, "out_of_range_count": outside_count,
            "coverage_seconds": covered, "coverage_fraction": covered / duration,
            "reasons": reasons,
            "state": "unusable" if unusable else ("review" if reasons else "no_rule_flag"),
        })
    return {
        "windows": windows, "artifact_intervals": artifacts,
        "run_duration_s": run_duration, "run_sample_count": int(high - low),
        "coverage_start_s": coverage_start, "coverage_stop_s": coverage_stop,
        "coverage_seconds": coverage_stop - coverage_start,
        "rules": {
            "window_seconds": 30, "window_membership": "[onset, end); final partial window retained",
            "adc_boundary": "finite values <= 0 or >= 4095",
            "clip_fraction_denominator": "finite samples in the window, not seconds",
            "clip_fraction_review_above": 0.01, "constant_span_review_above_s": 5.0,
            "constant_span": "(N - 1) / fs; continuous sequences identified across the run, then intersected with windows",
            "longest_constant_span_s": "full run-internal continuous segment touching the window, including any part outside that window",
            "unusable": "no samples, no finite samples, or fewer than 5 unique finite values",
            "artifact_duration_s": "first-to-last sample span (N - 1) / fs; single-sample interval has zero span",
            "artifact_support_duration_s": "sample support through last interval sample + 1/fs, clipped to run end and original array's last sample time",
            "artifact_overlap": "categories can overlap; use a union for total flagged support time",
            "coverage": "intersection with first-to-last original sample times; array's final sample is never extended by 1/fs",
            "interpretation": "fixed descriptive flags, not validated physiological usability",
        },
    }
