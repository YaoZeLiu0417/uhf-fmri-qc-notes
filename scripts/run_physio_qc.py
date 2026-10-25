"""Recording-level QC and derived phase/RVT export, not a RETROICOR design.

  python scripts/run_physio_qc.py
  python scripts/run_physio_qc.py S02_pre
  python scripts/run_physio_qc.py --puls a.puls --resp b.resp --out results/adhoc/x
"""
import argparse, json, os, sys, numpy as np
from _common import load_sessions, ROOT
from physio import load_pmu, qc_puls, qc_resp, alignment
from physio.qc import rate_series, cardiac_phase, respiratory_phase, rvt
from physio.plots import plot_qc


def _sample_phase(values, times, fs):
    out = np.full(times.shape, np.nan)
    if values is not None and len(values):
        valid = (times >= 0) & (times <= (len(values) - 1) / fs)
        out[valid] = values[np.rint(times[valid] * fs).astype(int)]
    return out


def derived_series(rec_p, rec_r, cp=None, rp=None, rvt_t=None, rvt_v=None):
    """Return separate clock-labelled tables unless both MDH starts are known."""
    clock = alignment(rec_p, rec_r) if rec_p is not None and rec_r is not None else None
    if rec_p is not None and rec_r is not None and clock is None:
        return (derived_series(rec_p, None, cp=cp) +
                derived_series(None, rec_r, rp=rp, rvt_t=rvt_t, rvt_v=rvt_v))
    off = clock["resp_start_minus_puls_start_s"] if clock else 0.0
    start = min(0.0, off) if rec_p is not None and rec_r is not None else 0.0
    stop = max(rec_p.duration_s if rec_p is not None else 0,
               off + rec_r.duration_s if rec_r is not None else 0)
    times = np.arange(np.ceil(start), stop, 1.0)
    c = _sample_phase(cp, times, rec_p.fs) if rec_p is not None else np.full(times.shape, np.nan)
    rt = times - off
    r = _sample_phase(rp, rt, rec_r.fs) if rec_r is not None else np.full(times.shape, np.nan)
    v = np.interp(rt, rvt_t, rvt_v, left=np.nan, right=np.nan) if rvt_t is not None and len(rvt_t) else np.full(times.shape, np.nan)
    return [{"clock": "PULS" if rec_p is not None else "RESP", "alignment": clock,
             "values": np.column_stack([times, c, r, v])}]


def run(puls, resp, out):
    report, panels, rvt_t, rvt_v, rec_p, rec_r, cp, rp = {}, [], None, None, None, None, None, None
    if puls:
        rec_p = load_pmu(puls)
        rep, beats = qc_puls(rec_p)
        report["puls"] = rep
        if beats is not None:
            panels.append(("PPG pulse rate (bpm)", *rate_series(beats, rec_p.fs, total_s=rec_p.duration_s)))
            cp = cardiac_phase(len(rec_p.signal), beats)
    if resp:
        rec_r = load_pmu(resp)
        rep, (pk, tr, y) = qc_resp(rec_r)
        report["resp"] = rep
        if not rep["verdict"].startswith("FAIL"):
            panels.append(("breaths / min", *rate_series(pk, rec_r.fs, total_s=rec_r.duration_s)))
            rvt_t = np.arange(0, rec_r.duration_s, 1.0)
            rvt_v = rvt(y, pk, tr, rec_r.fs, rvt_t)
            rp = respiratory_phase(y)
    if rec_p is not None and rec_r is not None:
        report["alignment"] = alignment(rec_p, rec_r)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    report["derived_exports"] = []
    for i, series in enumerate(derived_series(rec_p, rec_r, cp, rp, rvt_t, rvt_v)):
        suffix = "_regressors_1Hz.tsv" if i == 0 else "_resp_regressors_1Hz.tsv"
        note = ("MDH start-clock alignment assumed; not independently synchronized." if series["alignment"] else
                "Independent channel clock; other-channel values are unavailable, not aligned.")
        header = (f"# Recording-level derived estimates; 1 Hz is not fMRI cardiac-phase sampling or a RETROICOR design. "
                  f"t_s is seconds from {series['clock']} log start. {note}\n"
                  "t_s\tcardiac_phase\tresp_phase\trvt")
        np.savetxt(out + suffix, series["values"], delimiter="\t", fmt="%.4f", header=header, comments="")
        report["derived_exports"].append({"file": os.path.basename(out + suffix), "clock": series["clock"],
                                         "finite_values_per_column": np.isfinite(series["values"][:, 1:]).sum(axis=0).tolist()})
    report["derived_scope"] = "Recording-level phase/RVT estimates, without window-level physiological validation or acquisition-sampled RETROICOR harmonics."
    plot_qc(panels, rvt_t, rvt_v, out, "Physio QC (each channel's own elapsed time): " + ", ".join(os.path.basename(p) for p in (puls, resp) if p))
    with open(out + ".json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("session", nargs="?"); ap.add_argument("--puls"); ap.add_argument("--resp")
    ap.add_argument("--out"); ap.add_argument("--data-root"); a = ap.parse_args()
    if a.puls or a.resp:
        print(json.dumps(run(a.puls, a.resp, a.out or os.path.join(ROOT, "results", "adhoc", "qc")), indent=2)); sys.exit()
    S = load_sessions(a.data_root)
    for k, s in S.items():
        if a.session and k != a.session: continue
        r = run(s.get("puls"), s.get("resp"), os.path.join(s["out_dir"], "qc"))
        print(f"{k:14s} [{s['role']:10s}] puls: {r.get('puls', {}).get('verdict', '-'):55s} resp: {r.get('resp', {}).get('verdict', '-')}")
