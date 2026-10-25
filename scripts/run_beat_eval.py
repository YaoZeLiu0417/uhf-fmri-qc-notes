"""Evaluate offline PPG decisions against the scanner's physiological pulse markers.

  python scripts/run_beat_eval.py                 # all sessions with a usable puls log
  python scripts/run_beat_eval.py S02_pre
  python scripts/run_beat_eval.py --puls file.puls --out results/adhoc/beats
Writes <out>.json (metrics) and <out>.png (20 s window + heart-rate trace).
"""
import argparse, json, os, sys
from _common import load_sessions, ROOT
from physio import load_pmu, is_flatline, evaluate_ppg
from physio.plots import plot_beats

def run(puls, out):
    rec = load_pmu(puls)
    if is_flatline(rec.signal):
        return {"file": os.path.basename(puls), "skipped": "constant/low-variation signal; cause not established"}
    res, x, det, ref = evaluate_ppg(rec.signal, rec.fs, rec.trigger_idx)
    res = {"file": os.path.basename(puls), "mode": "real", **res}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    reference = "scanner pulse markers" if len(rec.trigger_idx) else "alternate offline detector"
    plot_beats(x, rec.fs, ref, det, out, f"{os.path.basename(puls)} — pulse oximeter at {rec.fs:g} Hz; reference = {reference}")
    json.dump(res, open(out + ".json", "w"), indent=2)
    return res

def one_line(k, r):
    if "skipped" in r: return f"{k:14s} skipped: {r['skipped']}"
    v = r.get("vs_scanner_triggers")
    if not v: return f"{k:14s} no scanner pulse markers; alternate-detector comparison only"
    return f"{k:14s} scanner-marker agreement: {json.dumps(v)}; clipped {r['clipped_pct']}%"

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("session", nargs="?"); ap.add_argument("--puls"); ap.add_argument("--out"); ap.add_argument("--data-root")
    a = ap.parse_args()
    if a.puls:
        print(json.dumps(run(a.puls, a.out or os.path.join(ROOT, "results", "adhoc", "beats")), indent=2)); sys.exit()
    S = load_sessions(a.data_root); summary = {}
    for k, s in S.items():
        if a.session and k != a.session: continue
        if "puls" not in s: continue
        r = run(s["puls"], os.path.join(s["out_dir"], "beats")); summary[k] = r; print(one_line(k, r))
    if not a.session:
        json.dump(summary, open(os.path.join(ROOT, "results", "beat_eval_summary.json"), "w"), indent=2)
