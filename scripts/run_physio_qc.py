"""Run physiological QC (+ RETROICOR/RVT regressors, + puls/resp alignment) on one or all sessions.

  python scripts/run_physio_qc.py                    # all sessions in sessions.json
  python scripts/run_physio_qc.py S02_pre        # one session
  python scripts/run_physio_qc.py --puls a.puls --resp b.resp --out results/adhoc/x   # arbitrary files
"""
import argparse, json, os, sys, numpy as np
from _common import load_sessions, ROOT
from physio import load_pmu, qc_puls, qc_resp, alignment
from physio.qc import rate_series, cardiac_phase, respiratory_phase, rvt
from physio.plots import plot_qc

def run(puls, resp, out):
    report, panels, rvt_t, rvt_v, rec_p, rec_r = {}, [], None, None, None, None
    if puls:
        rec_p = load_pmu(puls); rep, beats = qc_puls(rec_p); report["puls"] = rep
        if beats is not None:
            panels.append(("HR (bpm)", *rate_series(beats, rec_p.fs, total_s=rec_p.duration_s)))
            report["_cardiac_phase"] = cardiac_phase(len(rec_p.signal), beats); report["_fs"] = rec_p.fs
    if resp:
        rec_r = load_pmu(resp); rep, (pk, tr, y) = qc_resp(rec_r); report["resp"] = rep
        panels.append(("breaths / min", *rate_series(pk, rec_r.fs, total_s=rec_r.duration_s)))
        rvt_t = np.arange(0, rec_r.duration_s, 1.0); rvt_v = rvt(y, pk, tr, rec_r.fs, rvt_t)
        report["_resp_phase"] = respiratory_phase(y); report["_fs"] = rec_r.fs
    if rec_p is not None and rec_r is not None:
        report["alignment"] = alignment(rec_p, rec_r)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if "_fs" in report:
        fs, off = report["_fs"], 0.0
        if report.get("alignment"): off = -report["alignment"]["resp_start_minus_puls_start_s"]   # put resp on the puls clock
        n = max(len(report.get("_cardiac_phase", [])), len(report.get("_resp_phase", [])))
        rows = ["# t_s = seconds on the PULS log clock (first puls sample = 0)." +
                (f" resp shifted by {off:+.3f} s using MDH footers." if report.get("alignment") else " puls and resp NOT aligned (footer missing).") +
                " Align to DICOM AcquisitionTime via puls_MDH_start.", "t_s\tcardiac_phase\tresp_phase\trvt"]
        cp, rp = report.get("_cardiac_phase"), report.get("_resp_phase")
        for i in range(0, n, int(fs)):
            t = i / fs; j = int(round((t - off) * fs))
            c = cp[i] if cp is not None and i < len(cp) else np.nan
            r = rp[j] if rp is not None and 0 <= j < len(rp) else np.nan
            v = np.interp(t - off, rvt_t, rvt_v) if rvt_v is not None else np.nan
            rows.append(f"{t:.1f}\t{c:.4f}\t{r:.4f}\t{v:.4f}")
        open(out + "_regressors_1Hz.tsv", "w").write("\n".join(rows))
    plot_qc(panels, rvt_t, rvt_v, out, "Physio QC: " + ", ".join(os.path.basename(p) for p in (puls, resp) if p))
    clean = {k: v for k, v in report.items() if not k.startswith("_")}
    json.dump(clean, open(out + ".json", "w"), indent=2)
    return clean

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
