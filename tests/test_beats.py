import numpy as np
import pytest
from physio.beats import causal_detect, score


def test_marker_matching_counts_and_offset_known_answer():
    result = score([100, 200, 300], [90, 190, 250, 290], 100, tol_s=.2, max_lag_s=.2)
    assert result['n_matched'] == 3
    assert result['n_unmatched_detection'] == 1
    assert result['sensitivity'] == 1
    assert result['ppv'] == .75
    assert result['offset_ms_median'] == pytest.approx(-100)
    assert result['timing_iqr_ms'] == pytest.approx(0)


def test_undefined_rates_and_invalid_events():
    result = score([], [], 100)
    assert result['sensitivity'] is None and result['ppv'] is None
    with pytest.raises(ValueError):
        score([2, 1], [1], 100)


def test_detector_without_global_cap_is_prefix_invariant_and_in_bounds():
    rng = np.random.default_rng(5)
    signal = rng.normal(size=2000)
    prefix = causal_detect(signal[:1000], 100, clip_pct=None)
    full = causal_detect(signal, 100, clip_pct=None)
    np.testing.assert_array_equal(prefix, full[full < 1000])
    assert (full < signal.size).all()
    assert causal_detect([], 100).size == 0
