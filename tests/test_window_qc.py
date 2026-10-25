"""Known sample clocks test window edges, constant spans and fixed thresholds."""
import numpy as np
import pytest

from physio.window_qc import window_qc


def ramp(n):
    return 1000 + 2 * (np.arange(n) % 100)


def test_half_open_membership_partial_last_window_and_conserved_duration():
    x = ramp(671)  # first/last sample at -1/66 s, including padding
    x[:10] = -1
    x[660:] = 5000  # time >=65 s must not enter this run
    report = window_qc(x, 10, -1, 65)
    windows = report["windows"]
    assert [w["n_samples"] for w in windows] == [300, 300, 50]
    assert [w["duration_s"] for w in windows] == [30, 30, 5]
    assert sum(w["n_samples"] for w in windows) == report["run_sample_count"] == 650
    assert sum(w["duration_s"] for w in windows) == 65
    assert sum(w["coverage_seconds"] for w in windows) == report["coverage_seconds"] == 65
    assert all(w["state"] == "no_rule_flag" for w in windows)
    assert report["artifact_intervals"] == []


def test_constant_segment_is_not_split_at_thirty_seconds():
    x = ramp(611)
    x[270:331] = 1111  # 27 through 33 seconds: 61 samples, 6-second span
    report = window_qc(x, 10, 0, 60)
    assert [w["longest_constant_span_s"] for w in report["windows"]] == [6, 6]
    assert all(w["state"] == "review" for w in report["windows"])
    interval, = report["artifact_intervals"]
    assert interval["kind"] == "long_constant"
    assert interval["onset_s"] == 27 and interval["duration_s"] == 6
    assert interval["support_duration_s"] == pytest.approx(6.1)
    assert (interval["sample_start"], interval["sample_stop"]) == (270, 331)


@pytest.mark.parametrize("n_constant, flagged", [(51, False), (52, True)])
def test_constant_threshold_uses_n_minus_one_not_sample_support(n_constant, flagged):
    x = ramp(301)
    x[100:100 + n_constant] = 1111
    report = window_qc(x, 10, 0, 30)
    row, = report["windows"]
    assert row["longest_constant_span_s"] == (n_constant - 1) / 10
    assert ("long_constant_span_gt_5s" in row["reasons"]) is flagged


@pytest.mark.parametrize("n_clipped, flagged", [(1, False), (2, True)])
def test_clipping_threshold_is_strict_sample_fraction(n_clipped, flagged):
    x = ramp(101)
    x[:n_clipped] = 0
    row, = window_qc(x, 10, 0, 10)["windows"]
    assert row["clip_fraction"] == n_clipped / 100
    assert ("adc_boundary_fraction_gt_0.01" in row["reasons"]) is flagged


def test_invalid_counts_exclude_nonfinite_from_clipping_denominator():
    x = ramp(101).astype(float)
    x[:6] = [-1, 0, 4095, 4096, np.nan, np.inf]
    report = window_qc(x, 10, 0, 10)
    row, = report["windows"]
    assert row["nonfinite_count"] == 2 and row["out_of_range_count"] == 2
    assert row["clip_count"] == 4 and row["clip_fraction"] == 4 / 98
    assert row["state"] == "review"
    by_kind = {}
    for interval in report["artifact_intervals"]:
        assert 0 <= interval["onset_s"] <= interval["end_s"] < 10
        assert interval["support_stop_s"] <= 10
        by_kind[interval["kind"]] = by_kind.get(interval["kind"], 0) + interval["support_duration_s"]
    assert by_kind == pytest.approx({"adc_boundary": .4, "nonfinite": .2, "out_of_range": .2})


def test_missing_samples_and_low_variation_are_not_unflagged():
    for x in ([], [2048], [np.nan] * 101, [1, 2, 3, 4] * 26):
        row, = window_qc(x, 10, 0, 10)["windows"]
        assert row["state"] == "unusable"
    row, = window_qc(ramp(51), 10, 5, 20)["windows"]
    assert row["coverage_seconds"] == 5
    assert row["coverage_fraction"] == .25
    assert row["state"] == "review" and "incomplete_coverage" in row["reasons"]


def test_original_last_sample_is_not_given_extra_support():
    x = ramp(100)  # final original sample at 9.9 s
    x[40:] = 1111
    report = window_qc(x, 10, 0, 10)
    assert report["coverage_stop_s"] == pytest.approx(9.9)
    interval, = report["artifact_intervals"]
    assert interval["duration_s"] == 5.9
    assert interval["support_duration_s"] == pytest.approx(5.9)
    assert interval["support_stop_s"] == pytest.approx(9.9)
    assert report["windows"][0]["state"] == "review"
