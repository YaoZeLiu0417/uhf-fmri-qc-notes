"""Recover per-run acquisition start times directly from DICOM when the raw BIDS sidecar is unavailable
(e.g. only DeepPrep/fMRIPrep derivatives are at hand). Nothing identifying is printed or written.

  python scripts/dicom_run_times.py /path/to/DICOM_root [--out runs.json]

Output per series: SeriesNumber, SeriesDescription, first AcquisitionDate/Time (0008,0022 / 0008,0032),
number of files (= volumes for single-frame EPI; for mosaic Siemens EPI each file is one volume), RepetitionTime (0018,0080).
Feed the AcquisitionTime values to the physio alignment (they share the wall clock with the PMU footer's MDH time).
"""
import argparse, json, os, sys
try:
    import pydicom
except ImportError:
    sys.exit("pip install pydicom")

def scan(root):
    series = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                d = pydicom.dcmread(p, stop_before_pixels=True, specific_tags=[
                    "SeriesNumber", "SeriesDescription", "AcquisitionDate", "AcquisitionTime", "RepetitionTime",
                    "InstanceNumber", "ProtocolName", "ImageType"])
            except Exception:
                continue
            k = int(getattr(d, "SeriesNumber", -1))
            s = series.setdefault(k, {"SeriesNumber": k, "SeriesDescription": str(getattr(d, "SeriesDescription", "")),
                                      "ProtocolName": str(getattr(d, "ProtocolName", "")), "RepetitionTime_ms": getattr(d, "RepetitionTime", None),
                                      "n_files": 0, "AcquisitionDate": None, "AcquisitionTime_first": None, "AcquisitionTime_last": None})
            s["n_files"] += 1
            t = str(getattr(d, "AcquisitionTime", "") or "")
            if t:
                if s["AcquisitionTime_first"] is None or t < s["AcquisitionTime_first"]:
                    s["AcquisitionTime_first"] = t; s["AcquisitionDate"] = str(getattr(d, "AcquisitionDate", ""))
                if s["AcquisitionTime_last"] is None or t > s["AcquisitionTime_last"]:
                    s["AcquisitionTime_last"] = t
    return [series[k] for k in sorted(series)]

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--out"); a = ap.parse_args()
    rows = scan(a.root)
    for r in rows:
        print(f"{r['SeriesNumber']:3d}  {r['SeriesDescription'][:40]:40s}  {r['AcquisitionTime_first'] or '-':>14s} .. {r['AcquisitionTime_last'] or '-':>14s}  "
              f"n={r['n_files']:4d}  TR={r['RepetitionTime_ms']} ms")
    if a.out:
        json.dump(rows, open(a.out, "w"), indent=2); print("written", a.out)
