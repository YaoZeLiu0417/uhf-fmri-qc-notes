"""Known-clock sampling and failure cases for recording-level physiology QC."""
import json
from pathlib import Path
import sys
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from physio.siemens_pmu import PMURecording
from physio import qc
import run_physio_qc as cli


def recording(kind, x, fs=100.0, start=None):
    footer = {} if start is None else {"LogStartMDHTime": start, "LogStopMDHTime": start + round((len(x) - 1) / fs * 1000)}
    return PMURecording(f"synthetic.{kind}", kind, 1, np.asarray(x), fs, np.array([], dtype=int), footer=footer)


def test_resp_14_seconds_earlier_uses_later_resp_samples_and_own_rate():
    puls = recording("puls", np.arange(2010), fs=50.25, start=14000)
    resp = recording("resp", np.arange(4830), fs=80.5, start=0)
    table, = cli.derived_series(puls, resp, cp=puls.signal, rp=resp.signal,
                               rvt_t=np.array([14.0, 15.0]), rvt_v=np.array([2.0, 3.0]))
    rows = table["values"]
    at_zero = rows[rows[:, 0] == 0][0]
    at_one = rows[rows[:, 0] == 1][0]
    assert table["alignment"]["resp_start_minus_puls_start_s"] == -14
    assert at_zero[1] == 0 and at_zero[2] == 1127 and at_zero[3] == 2
    assert at_one[1] == 50 and at_one[2] == 1208 and at_one[3] == 3
    assert np.isnan(rows[rows[:, 0] == -1][0, 1])
    assert np.isnan(rows[rows[:, 0] == 2][0, 3])  # no RVT edge extrapolation


def test_missing_clocks_export_separate_time_axes():
    puls = recording("puls", np.arange(1000))
    resp = recording("resp", np.arange(2000), fs=200)
    tables = cli.derived_series(puls, resp, cp=puls.signal, rp=resp.signal)
    assert [t["clock"] for t in tables] == ["PULS", "RESP"]
    assert np.isnan(tables[0]["values"][:, 2:]).all()
    assert np.isnan(tables[1]["values"][:, 1]).all()
    assert tables[1]["values"][1, 2] == 200


def test_phase_and_rvt_do_not_extrapolate_edges():
    sampled = cli._sample_phase(np.arange(11), np.array([-0.1, 0, 0.5, 1, 1.01]), 10)
    np.testing.assert_allclose(sampled, [np.nan, 0, 5, 10, np.nan], equal_nan=True)
    t = np.arange(13)
    y = 5 - 5 * np.cos(np.pi * t / 2)
    values = qc.rvt(y, [2, 6, 10], [0, 4, 8, 12], 1, [0, 5.9, 6, 8, 10, 10.1, 20])
    np.testing.assert_allclose(values, [np.nan, np.nan, 2.5, 2.5, 2.5, np.nan, np.nan], equal_nan=True)
    assert np.isnan(qc.rvt(y, [], [], 1, [0, 1])).all()


@pytest.mark.parametrize("x", [[], [2048] * 100, list(range(10)), [np.nan] * 100])
def test_unusable_signals_return_no_valid_rate_or_phase(x):
    pp, beats = qc.qc_puls(recording("puls", x))
    rr, (peaks, troughs, y) = qc.qc_resp(recording("resp", x))
    assert pp["verdict"].startswith("FAIL") and rr["verdict"].startswith("FAIL")
    assert pp["pulse_rate_bpm_median"] is None and rr["rr_per_min_median"] is None
    assert beats is None and not len(peaks) and not len(troughs)
    assert np.isnan(qc.respiratory_phase(y)).all()
    assert "sensor not connected" not in pp["verdict"]
    json.dumps([pp, rr], allow_nan=False)


def test_no_detected_events_return_unavailable_not_zero_rate(monkeypatch):
    x = np.arange(1000)
    monkeypatch.setattr(qc, "offline_detect", lambda *a: (np.array([], dtype=int), x))
    monkeypatch.setattr(qc, "find_peaks", lambda *a, **kw: (np.array([], dtype=int), {}))
    pp, beats = qc.qc_puls(recording("puls", x))
    rr, events = qc.qc_resp(recording("resp", x))
    assert beats is None and pp["pulse_rate_bpm_median"] is None
    assert rr["rr_per_min_median"] is None and rr["verdict"].startswith("FAIL")
    assert np.isnan(qc.rate_series([], 100, total_s=120)[1]).all()
    assert len(qc.rate_series([], 100)[0]) == 0


@pytest.mark.parametrize("constant_samples, expected", [(500, "OK"), (600, "WARN")])
def test_resp_long_constant_segment_is_a_descriptive_warning(constant_samples, expected):
    t = np.arange(12000) / 100
    x = 2048 + 500 * np.sin(2 * np.pi * 0.25 * t)
    x[3025:3025 + constant_samples] = 1111
    report, _ = qc.qc_resp(recording("resp", x, start=0))
    assert report["longest_constant_run_s"] == constant_samples / 100
    assert report["verdict"].split(":")[0] == expected
    assert ("constant segment" in report["verdict"]) == (expected == "WARN")
    assert "sensor" not in report["verdict"]


def test_cli_flat_recordings_write_explicit_missing_values(tmp_path, monkeypatch):
    records = {"p": recording("puls", np.full(1000, 2048)), "r": recording("resp", np.full(1000, 2048))}
    monkeypatch.setattr(cli, "load_pmu", records.__getitem__)
    monkeypatch.setattr(cli, "plot_qc", lambda *a: None)
    report = cli.run("p", "r", str(tmp_path / "qc"))
    assert report["alignment"] is None
    assert len(report["derived_exports"]) == 2
    for entry in report["derived_exports"]:
        path = tmp_path / entry["file"]
        assert "not fMRI" in path.read_text()
        values = np.loadtxt(path, delimiter="\t", skiprows=2)
        assert np.isnan(values[:, 1:]).all()
    assert json.loads((tmp_path / "qc.json").read_text())["puls"]["pulse_rate_bpm_median"] is None
