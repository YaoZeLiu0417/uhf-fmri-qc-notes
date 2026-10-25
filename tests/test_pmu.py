"""Known-answer PMU cases; no participant data are needed."""
import numpy as np
import pytest

from physio.siemens_pmu import PMURecording, load_pmu


def write_log(tmp_path, trace, kind="PULS", version=1, footer="", end=True):
    path = tmp_path / "synthetic.pmu"
    path.write_text(
        f"1 2 40 280 5002 LOGVERSION_{kind} {version} 6002 {trace}"
        + (" 5003\n" if end else "") + footer,
        encoding="ascii",
    )
    return path


def test_messages_keep_early_samples_and_physiological_marker_positions(tmp_path):
    path = write_log(
        tmp_path, "10 5000 20 5002 note 5003 inside message 6002 6000 30",
        footer="LogStartMDHTime: 1000\nLogStopMDHTime: 1020\nPULS Freq Per: 60 1000",
    )
    rec = load_pmu(path)
    np.testing.assert_array_equal(rec.signal, [10, 20, 30])
    np.testing.assert_array_equal(rec.trigger_idx, [1])
    np.testing.assert_array_equal(rec.t, [0, 0.01, 0.02])
    assert rec.fs == 100 and rec.fs_source == "mdh_endpoints"
    assert rec.sample_span_s == rec.footer_duration_s() == 0.02
    assert rec.duration_s == 0.03  # existing API retains its N/fs extent
    assert rec.messages == ["note 5003 inside message"]
    assert rec.header_integers == [1, 2, 40, 280]
    assert rec.end_marker_present and not rec.warnings


def test_resp_three_keeps_all_aux_columns_and_exact_delimiter_boundaries(tmp_path):
    path = write_log(
        tmp_path, "10 1 2 3 4 5000 5002 gain 9 6002 20 15003 7 8 9 6000",
        kind="RESP", version=3,
        footer="LogStartMDHTime: 1000\nLogStopMDHTime: 1001",
    )
    rec = load_pmu(path)
    np.testing.assert_array_equal(rec.signal, [10, 20])
    np.testing.assert_array_equal(rec.aux, [[1, 2, 3, 4], [15003, 7, 8, 9]])
    np.testing.assert_array_equal(rec.trigger_idx, [1])
    assert rec.fs == 1000


def test_resp_one_and_missing_metadata_use_explicit_default(tmp_path):
    rec = load_pmu(write_log(tmp_path, "10 20 30", kind="RESP", end=False), fs_default=50)
    np.testing.assert_array_equal(rec.signal, [10, 20, 30])
    assert rec.aux is None and rec.fs == 50 and rec.fs_source == "default"
    assert rec.footer == {} and rec.footer_duration_s() is None
    assert not rec.end_marker_present and len(rec.warnings) == 2
    assert all("not stopped" not in message for message in rec.warnings)


def test_marker_digits_inside_aux_values_are_not_delimiters(tmp_path):
    rec = load_pmu(write_log(tmp_path, "10 15003 50001 60001 4", kind="RESP", version=3, end=False))
    np.testing.assert_array_equal(rec.signal, [10])
    np.testing.assert_array_equal(rec.aux, [[15003, 50001, 60001, 4]])
    assert not rec.end_marker_present and rec.trigger_idx.size == 0


def test_only_explicit_hardware_region_discards_training(tmp_path):
    path = write_log(tmp_path, "1 2 5002 uiHwRevisionPeru 7 6002 10 5002 gain 2 6002 20")
    rec = load_pmu(path)
    np.testing.assert_array_equal(rec.signal, [10, 20])
    assert rec.training_samples_discarded == 2
    assert rec.messages == ["uiHwRevisionPeru 7", "gain 2"]


@pytest.mark.parametrize("trace", ["1 2 3 4", "1 2 3 4 5 6", "5002 unclosed", "1 ++2 3 4 5"])
def test_incomplete_groups_and_malformed_tokens_are_rejected(tmp_path, trace):
    with pytest.raises(ValueError):
        load_pmu(write_log(tmp_path, trace, kind="RESP", version=3))


@pytest.mark.parametrize("token", ["9223372036854775808", "-9223372036854775809", "+9223372036854775808", "9" * 100, "-" + "9" * 100])
def test_integer_overflow_is_rejected_before_numpy_can_saturate(tmp_path, token):
    with pytest.raises(ValueError, match="64-bit"):
        load_pmu(write_log(tmp_path, f"10 {token} 20"))


def test_int64_limits_and_leading_zero_values_are_preserved(tmp_path):
    rec = load_pmu(write_log(tmp_path, "9223372036854775807 -9223372036854775808 +000000000000000000001"))
    np.testing.assert_array_equal(rec.signal, [9223372036854775807, -9223372036854775808, 1])


@pytest.mark.parametrize("kind,version", [("PULS", 3), ("RESP", 2), ("ECG", 1)])
def test_unsupported_formats_are_rejected(tmp_path, kind, version):
    with pytest.raises(ValueError, match="Unsupported"):
        load_pmu(write_log(tmp_path, "1 2 3", kind=kind, version=version))


@pytest.mark.parametrize("start,stop", [(86399000, 1000), (1000, 1000)])
def test_midnight_or_non_increasing_clock_is_not_silently_unwrapped(tmp_path, start, stop):
    with pytest.raises(ValueError, match="midnight"):
        load_pmu(write_log(tmp_path, "10 20", footer=f"LogStartMDHTime: {start}\nLogStopMDHTime: {stop}"))


def test_existing_positional_recording_constructor_is_compatible():
    rec = PMURecording("synthetic", "puls", 1, np.array([1, 2]), 50, np.array([1]), None, [], {})
    assert rec.fs_source == "default" and rec.sample_span_s == 0.02
