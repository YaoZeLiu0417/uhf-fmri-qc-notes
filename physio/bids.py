"""Export audited run windows from Siemens PMU logs without inferring MRI triggers.

Private manifests contain ``runs`` with BIDS filename prefixes as ``run_id``
(e.g. ``sub-01_ses-pre_task-rest_run-1``), ``volume_start`` (seconds since
midnight, or an explicit HH:MM:SS.fraction string), ``duration_seconds``, and
``puls`` and/or ``resp`` paths. Relative paths resolve beside the manifest.
The supplied onset must already have been audited against the stored MRI run.
"""
from __future__ import annotations

from collections import defaultdict
import gzip
import io
import json
import math
from pathlib import Path
import re

import numpy as np

from .siemens_pmu import load_pmu


RUN_ID = re.compile(
    r"(?P<subject>sub-[A-Za-z0-9]+)(?:_(?P<session>ses-[A-Za-z0-9]+))?"
    r"_task-(?P<task>[A-Za-z0-9]+)(?:_acq-[A-Za-z0-9]+)?(?:_run-[0-9]+)?"
)
CHANNELS = {"puls": "cardiac", "resp": "respiratory"}


def onset_seconds(value) -> float:
    """Accept explicit clock notation; never interpret numeric HHMMSS."""
    if isinstance(value, str):
        match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", value)
        if not match:
            raise ValueError("volume_start requires seconds or HH:MM:SS.fraction")
        hours, minutes, seconds = map(float, match.groups())
        if hours >= 24 or minutes >= 60 or seconds >= 60:
            raise ValueError("volume_start clock is out of range")
        value = hours * 3600 + minutes * 60 + seconds
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("volume_start must be a number or explicit clock string")
    if not math.isfinite(value) or not 0 <= value < 86400:
        raise ValueError("volume_start must be within one scanner-clock day")
    return float(value)


def extract_segment(recording, volume_start, duration_seconds):
    """Return source samples, BIDS metadata and half-open source slice indices.

    Endpoints, rather than the parser's fallback rate, determine the effective
    sample spacing. No midnight rollover or missing scanner TTL is guessed.
    """
    start = onset_seconds(volume_start)
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)):
        raise ValueError("invalid_duration")
    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration <= 0 or start + duration >= 86400:
        raise ValueError("invalid_duration_or_cross_midnight_run")
    signal = np.asarray(recording.signal)
    if signal.ndim != 1 or signal.size < 2 or not np.all(np.isfinite(signal)):
        raise ValueError("invalid_signal")
    if recording.kind not in CHANNELS:
        raise ValueError("unsupported_channel")
    first = recording.footer.get("LogStartMDHTime")
    last = recording.footer.get("LogStopMDHTime")
    if first is None or last is None:
        raise ValueError("missing_mdh_clock")
    first, last = float(first) / 1000, float(last) / 1000
    if not (math.isfinite(first) and math.isfinite(last) and 0 <= first < last < 86400):
        raise ValueError("invalid_mdh_clock_or_midnight_rollover")
    stop = start + duration
    if start < first or stop > last:
        raise ValueError("insufficient_time_coverage")
    fs = (signal.size - 1) / (last - first)
    low = max(0, math.ceil((start - 5 - first) * fs))
    high = min(signal.size, math.floor((stop + 5 - first) * fs) + 1)
    segment = signal[low:high]
    # Check only samples in [start, stop); neighboring padding cannot rescue a
    # flat run, and a sample at the stop boundary belongs to the next interval.
    run_low = max(0, math.ceil((start - first) * fs))
    run_high = min(signal.size, math.ceil((stop - first) * fs))
    run_signal = signal[run_low:run_high]
    if not run_signal.size:
        raise ValueError("no_samples_during_run")
    if np.ptp(run_signal) == 0:
        raise ValueError("constant_signal_during_run")
    channel = CHANNELS[recording.kind]
    metadata = {
        "SamplingFrequency": fs,
        "StartTime": first + low / fs - start,
        "Columns": [channel],
        "PhysioType": "generic",
        channel: {
            "Units": "a.u.",
            "Description": ("Uncalibrated pulse oximeter waveform (PPG), not ECG or heart rate."
                            if channel == "cardiac" else "Uncalibrated breathing-belt waveform."),
        },
        "Synchronization": "Externally audited stored-volume onset supplied in the private manifest; aligned to Siemens MDH clock endpoints. No MRI TTL pulses are inferred or verified.",
        "SamplingFrequencyMethod": "(number of source samples - 1) / MDH endpoint duration; assumes uniform sampling between endpoints. This does not establish hardware sampling rate, absence of dropped samples, jitter, or nonlinear clock drift.",
        "PaddingSecondsRequested": 5,
        "PaddingDescription": "Up to five seconds of original samples on each side; no padding or interpolation is synthesized.",
        "SourceSliceStart": low,
        "SourceSliceStop": high,
    }
    return segment, metadata, (low, high)


def _write_segment(tsv: Path, metadata: dict, samples: np.ndarray) -> None:
    sidecar = tsv.with_name(tsv.name.removesuffix(".tsv.gz") + ".json")
    if tsv.exists() or sidecar.exists():
        raise FileExistsError("output_exists")
    tsv.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with tsv.open("xb") as raw:
            created.append(tsv)
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="ascii", newline="\n") as stream:
                    np.savetxt(stream, samples, fmt="%d")
        with gzip.open(tsv, "rt", encoding="ascii") as stream:
            restored = np.loadtxt(stream, dtype=samples.dtype, ndmin=1)
        if not np.array_equal(restored, samples):
            raise ValueError("export_readback_mismatch")
        with sidecar.open("x", encoding="utf-8", newline="\n") as stream:
            created.append(sidecar)
            json.dump(metadata, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except Exception:
        for path in created:
            path.unlink()
        raise


def export_manifest(manifest_path, out) -> dict:
    """Export independent run/channel pairs; return a path/clock-free report.

    Existing outputs are refused, including incomplete pairs. Invalid manifest
    structure or output placement fails before any export. Channel failures are
    reported independently so a missing pulse never becomes synthetic data.
    """
    manifest_path, out = Path(manifest_path).resolve(), Path(out).resolve()
    with manifest_path.open(encoding="utf-8-sig") as stream:
        manifest = json.load(stream)
    runs = manifest.get("runs") if isinstance(manifest, dict) else None
    if not isinstance(runs, list) or not runs:
        raise ValueError("manifest requires a nonempty runs list")
    jobs = defaultdict(list)
    seen = set()
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str):
            raise ValueError("run requires an anonymous BIDS run_id")
        run_id = run["run_id"]
        match = RUN_ID.fullmatch(run_id)
        if not match or run_id.casefold() in seen:
            raise ValueError("run_id must be a unique BIDS prefix with sub and task")
        seen.add(run_id.casefold())
        start = onset_seconds(run.get("volume_start"))
        duration = run.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0 or start + duration >= 86400:
            raise ValueError("invalid_duration_or_cross_midnight_run")
        if not any(run.get(kind) for kind in CHANNELS):
            raise ValueError("run requires at least one puls or resp source")
        directory = out / match["subject"]
        if match["session"]:
            directory /= match["session"]
        directory /= "func"
        for kind, channel in CHANNELS.items():
            if not run.get(kind):
                continue
            if not isinstance(run[kind], str):
                raise ValueError("source path must be a string")
            source = (manifest_path.parent / run[kind]).resolve()
            target = directory / f"{run_id}_recording-{channel}_physio.tsv.gz"
            jobs[source].append((run_id, kind, start, duration, target))
    sources = list(jobs)
    for entries in jobs.values():
        for _, _, _, _, target in entries:
            for source in sources:
                if out == source or out.is_relative_to(source.parent) or target.resolve().is_relative_to(source.parent):
                    raise ValueError("output must be separate from raw input directories")
            if target.resolve() == manifest_path:
                raise ValueError("output_conflicts_with_manifest")
    results = []
    for source, entries in jobs.items():
        try:
            recording = load_pmu(str(source))
        except (OSError, ValueError):
            recording = None
        for run_id, kind, start, duration, target in entries:
            item = {"run_id": run_id, "recording": CHANNELS[kind]}
            try:
                if recording is None:
                    raise ValueError("source_unreadable_or_invalid")
                if recording.kind != kind:
                    raise ValueError("source_channel_mismatch")
                samples, metadata, _ = extract_segment(recording, start, duration)
                metadata["TaskName"] = RUN_ID.fullmatch(run_id)["task"]
                _write_segment(target, metadata, samples)
                item.update(status="exported", samples=int(samples.size),
                            SamplingFrequency=metadata["SamplingFrequency"],
                            StartTime=metadata["StartTime"])
            except FileExistsError:
                item.update(status="rejected", reason="output_exists")
            except ValueError as exc:
                item.update(status="rejected", reason=str(exc))
            except OSError:
                item.update(status="rejected", reason="output_io_error")
            results.append(item)
    return {"runs": len(runs), "exported": sum(x["status"] == "exported" for x in results),
            "rejected": sum(x["status"] == "rejected" for x in results), "recordings": results}
