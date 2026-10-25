"""Evaluate an explicit private recording manifest and write aggregate measurements.

No paths, participant identifiers, absolute clock times or waveforms enter the
aggregate output. --details is optional and must remain private. This evaluates
recording quality and offline marker agreement, not interoceptive perception.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physio import load_pmu, is_flatline, qc_puls, qc_resp, evaluate_ppg
from physio.beats import score


def distribution(values):
    values = np.asarray([x for x in values if x is not None and np.isfinite(x)], float)
    if not values.size:
        return {"n": 0, "minimum": None, "median": None, "maximum": None}
    return {"n": len(values), "minimum": float(values.min()),
            "median": float(np.median(values)), "maximum": float(values.max())}


def validate_recordings(recordings):
    if not isinstance(recordings, list) or not recordings:
        raise ValueError("Manifest requires a nonempty recordings list")
    for row in recordings:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                for key in ("recording_id", "participant_id", "visit_id")):
            raise ValueError("Each visit requires recording_id, participant_id and visit_id strings")
    ids = [row["recording_id"] for row in recordings]
    visits = [(row["participant_id"], row["visit_id"]) for row in recordings]
    if len(ids) != len(set(ids)) or len(visits) != len(set(visits)):
        raise ValueError("Use one unique recording_id row per participant/visit")
    for row in recordings:
        paths = [row.get(channel) for channel in ("puls", "resp")]
        if any(path is not None and (not isinstance(path, str) or not path.strip()) for path in paths):
            raise ValueError("Channel paths must be nonempty strings when supplied")
        if not any(paths):
            raise ValueError("Each visit requires at least one puls or resp source")


def evaluate(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recordings = manifest["recordings"]
    validate_recordings(recordings)
    details, seen_paths, seen_hashes = [], set(), set()
    for item in recordings:
        for channel in ("puls", "resp"):
            if not item.get(channel):
                continue
            path = (manifest_path.parent / item[channel]).resolve()
            if path in seen_paths:
                raise ValueError("The same source cannot be counted twice")
            seen_paths.add(path)
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if source_hash in seen_hashes:
                raise ValueError("Duplicate source content cannot be counted as another recording")
            seen_hashes.add(source_hash)
            rec = load_pmu(str(path))
            if rec.kind != channel:
                raise ValueError("Manifest channel does not match PMU header")
            qc, _ = qc_puls(rec) if channel == "puls" else qc_resp(rec)
            row = {
                "recording_id": item["recording_id"], "participant_id": item["participant_id"],
                "visit_id": item["visit_id"],
                "channel": channel, "source_sha256": source_hash,
                "samples": len(rec.signal), "sample_span_minutes": (len(rec.signal)-1)/rec.fs/60,
                "sampling_frequency": rec.fs,
                "fs_source": rec.fs_source, "footer_complete": all(k in rec.footer for k in
                    ("LogStartMDHTime", "LogStopMDHTime", "LogStartMPCUTime", "LogStopMPCUTime")),
                "constant_signal": bool(np.ptp(rec.signal) == 0),
                "physiological_marker_count": len(rec.trigger_idx),
                "gain_message_count": sum("gain" in x.lower() for x in rec.messages),
                "qc": {k: v for k, v in qc.items() if k != "file"},
            }
            if channel == "puls":
                if is_flatline(rec.signal) or rec.duration_s < 30:
                    row["evaluation_skipped"] = "constant/low-variation or short record"
                elif not len(rec.trigger_idx):
                    row["evaluation_skipped"] = "no scanner pulse-marker reference"
                else:
                    metrics, _, detected, _ = evaluate_ppg(rec.signal, rec.fs, rec.trigger_idx)
                    row["marker_comparison"] = metrics["vs_scanner_triggers"]
                    row["narrow_window_comparison"] = score(rec.trigger_idx, detected, rec.fs, tol_s=.15, max_lag_s=.3)
            details.append(row)
            print(f"Processed {len(details)} channel recordings", flush=True)
    return aggregate(details, recordings), details


def aggregate(details, recordings):
    validate_recordings(recordings)
    summary = {
        "scope": "MRI physiological measurement: recording QC, clock provenance, offline PPG marker comparison. No brain/BOLD association, clinical outcome or perception inference.",
        "participants": len({x["participant_id"] for x in recordings}),
        "visits": len(recordings), "channel_recordings": len(details),
        "recording_quality": {},
        "measurement_limits": [
            "MDH-derived effective sampling rates assume uniform within-recording sampling; fallback rates are counted separately.",
            "Scanner physiological markers are not independent ECG ground truth or MRI TTL.",
            "The evaluated detector uses a whole-record percentile cap and is offline.",
            "Timing offsets are marker-relative, not system latency or R-peak errors.",
            "Quality checks do not validate respiratory phase, RVT, perception or real-time closed-loop operation.",
            "Repeated visits and individual pulse events are not independent participants.",
        ],
    }
    for channel in ("puls", "resp"):
        rows = [x for x in details if x["channel"] == channel]
        long_rows = [x for x in rows if not x["constant_signal"] and x["sample_span_minutes"] >= .5]
        mdh_rows = [x for x in long_rows if x["fs_source"] == "mdh_endpoints"]
        summary["recording_quality"][channel] = {
            "recordings": len(rows), "complete_clock_footers": sum(x["footer_complete"] for x in rows),
            "constant_recordings": sum(x["constant_signal"] for x in rows),
            "nonconstant_long_recordings": len(long_rows),
            "nonconstant_long_recorded_minutes": sum(x["sample_span_minutes"] for x in long_rows),
            "fallback_sampling_rate_recordings": sum(x["fs_source"] != "mdh_endpoints" for x in rows),
            "long_record_effective_hz": distribution([x["sampling_frequency"] for x in mdh_rows]),
            "adc_clipping_percent": distribution([x["qc"].get("clipped_pct") for x in rows]),
            "longest_constant_seconds": distribution([x["qc"].get("longest_constant_run_s") for x in rows]),
            "records_with_gain_messages": sum(x["gain_message_count"] > 0 for x in rows),
            "qc_verdict_counts": {label: sum(x["qc"]["verdict"].startswith(label) for x in rows) for label in ("OK", "WARN", "FAIL")},
        }
    evaluated = [x for x in details if "marker_comparison" in x]
    summary["offline_ppg_evaluation"] = {
        "participants": len({x["participant_id"] for x in evaluated}),
        "recordings": len(evaluated),
        "recorded_minutes": sum(x["sample_span_minutes"] for x in evaluated),
        "detector_change": "Trailing average now retains original sample count and correct sample indexing; detector parameters unchanged. Historical metrics are not overwritten.",
    }
    for label, field in (("historical_window", "marker_comparison"), ("narrower_window_sensitivity", "narrow_window_comparison")):
        scores = [x[field] for x in evaluated]
        n_ref = sum(x["n_ref"] for x in scores)
        n_det = sum(x["n_det"] for x in scores)
        matched = sum(x["n_matched"] for x in scores)
        summary["offline_ppg_evaluation"][label] = {
            "matching_window_seconds": scores[0]["matching_window_seconds"] if scores else None,
            "reference_markers": n_ref, "detections": n_det, "matched_pairs": matched,
            "pooled_reference_recall": matched/n_ref if n_ref else None,
            "pooled_detection_ppv": matched/n_det if n_det else None,
            "per_record_distributions": {key: distribution([x.get(key) for x in scores]) for key in
                ("sensitivity", "ppv", "offset_ms_median", "timing_iqr_ms", "timing_sd_ms", "outliers_pct_beyond_100ms")},
        }
    code_paths = ["physio/siemens_pmu.py", "physio/beats.py", "physio/qc.py", "scripts/evaluate_cohort.py"]
    summary["implementation_sha256"] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in code_paths}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Aggregate JSON; safe to review before publication")
    parser.add_argument("--details", type=Path, help="Optional participant-level JSON; keep private")
    args = parser.parse_args()
    if args.details is not None and args.out.resolve() == args.details.resolve():
        raise ValueError("Aggregate and private details must use different output files")
    for output in (args.out, args.details):
        if output is not None and (output.exists() or output.resolve() == args.manifest.resolve()):
            raise ValueError("Choose new output files; existing files are not overwritten")
    summary, details = evaluate(args.manifest)
    for output, data in ((args.out, summary), (args.details, details)):
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(data, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
