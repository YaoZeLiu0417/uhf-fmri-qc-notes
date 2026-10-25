"""Pair locations for descriptive PPG-marker audits, without declaring truth."""
import numpy as np


def event_pairs(reference_s, detected_s, before_s=.3, after_s=.6):
    """Return earliest-available one-to-one pairs under the legacy score rule.

    Pair over a complete run before assigning each side to a display window.
    The reference can be a same-sensor scanner marker and is not ECG truth.
    """
    reference_s, detected_s = np.asarray(reference_s, float), np.asarray(detected_s, float)
    if not np.isfinite([before_s, after_s]).all() or min(before_s, after_s) < 0:
        raise ValueError('Invalid matching interval')
    for events in (reference_s, detected_s):
        if events.ndim != 1 or not np.isfinite(events).all() or np.any(events < 0) or np.any(np.diff(events) <= 0):
            raise ValueError('Events must be finite, nonnegative and strictly increasing')
    used = np.zeros(len(detected_s), bool)
    pairs = []
    for i, time in enumerate(reference_s):
        j = np.searchsorted(detected_s, time-before_s)
        while j < len(detected_s) and detected_s[j] <= time+after_s:
            if not used[j]:
                used[j] = True
                pairs.append((i, j))
                break
            j += 1
    return np.asarray(pairs, dtype=int).reshape(-1, 2)


def window_pair_report(reference_s, detected_s, pairs, start_s, end_s):
    """Report both sides of globally paired events within a half-open window.

    A pair can cross a window boundary. Reference-side and detection-side
    matched counts are therefore kept separate, including their denominators.
    """
    reference_s, detected_s = np.asarray(reference_s), np.asarray(detected_s)
    pairs = np.asarray(pairs, int).reshape(-1, 2)
    ref_inside = (reference_s >= start_s) & (reference_s < end_s)
    det_inside = (detected_s >= start_s) & (detected_s < end_s)
    matched_ref = int(ref_inside[pairs[:, 0]].sum())
    matched_det = int(det_inside[pairs[:, 1]].sum())
    n_ref, n_det = int(ref_inside.sum()), int(det_inside.sum())
    selected = pairs[ref_inside[pairs[:, 0]]]
    offsets = (detected_s[selected[:, 1]]-reference_s[selected[:, 0]])*1000
    return {
        'reference_events': n_ref, 'detected_events': n_det,
        'matched_reference_events': matched_ref, 'matched_detection_events': matched_det,
        'unmatched_reference_events': n_ref-matched_ref,
        'unmatched_detection_events': n_det-matched_det,
        'reference_marker_coverage': matched_ref/n_ref if n_ref else None,
        'matched_detection_fraction': matched_det/n_det if n_det else None,
        'median_detection_minus_marker_ms': float(np.median(offsets)) if offsets.size else None,
        'matched_offset_iqr_ms': float(np.subtract(*np.percentile(offsets,[75,25]))) if offsets.size else None,
        'offset_basis': 'Pairs whose reference event lies inside the window; matched events only.',
    }
