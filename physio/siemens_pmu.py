"""Read the observed Siemens PULS v1 and RESP v1/v3 manual PMU logs.

RESP v3 stores five integers per sample; all four auxiliary columns are kept.
5000/6000 are physiological peak markers, not verified MRI TTL pulses. MDH
endpoints estimate a uniform effective sample rate, not the hardware rate or
proof that no samples were dropped. Missing metadata does not explain its cause.
"""
from __future__ import annotations

import re
import warnings as python_warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class PMURecording:
    path: str
    kind: str
    logversion: int
    signal: np.ndarray
    fs: float
    trigger_idx: np.ndarray  # legacy name: 5000 physiological marker sample indices
    aux: np.ndarray | None = None
    messages: list = field(default_factory=list)
    footer: dict = field(default_factory=dict)
    fs_source: str = "default"
    warnings: list[str] = field(default_factory=list)
    header_integers: list[int] = field(default_factory=list)
    end_marker_present: bool = False
    training_samples_discarded: int = 0

    @property
    def duration_s(self) -> float:
        """Historical N/fs extent; use sample_span_s for first-to-last duration."""
        return len(self.signal) / self.fs

    @property
    def sample_span_s(self) -> float:
        return max(0, len(self.signal) - 1) / self.fs

    @property
    def t(self) -> np.ndarray:
        return np.arange(len(self.signal)) / self.fs

    def footer_duration_s(self) -> float | None:
        a, b = self.footer.get("LogStartMDHTime"), self.footer.get("LogStopMDHTime")
        if a is None or b is None:
            return None
        if b <= a:
            raise ValueError("Non-increasing MDH endpoints; midnight rollover or invalid dates require explicit resolution")
        return (b - a) / 1000.0


def _parse_footer(text: str) -> dict:
    out = {key: int(value) for key, value in re.findall(r"\b(Log\w+Time):\s*(\d+)", text)}
    for line in text.splitlines():
        match = re.match(r"\s*(\w+)\s+(Freq Per|Min Max Avg StdDiff):\s+([\d \t]+)", line)
        if match:
            out[f"{match[1]}_{match[2].replace(' ', '')}"] = [int(x) for x in match[3].split()]
    return out


_MESSAGE = re.compile(rb"(?<!\S)5002\s+(.*?)\s+6002(?!\S)", re.DOTALL)


def _values(trace: bytes) -> np.ndarray:
    """Reject malformed tokens instead of accepting NumPy's partial parses."""
    if re.search(rb"[^0-9\s+-]", trace):
        raise ValueError("Unexpected nonnumeric PMU trace token or unclosed message")
    # np.fromstring can silently saturate overflowing integers rather than raise.
    for match in re.finditer(rb"(?<!\S)[+-]?\d{19,}(?!\S)", trace):
        token = match[0]
        digits = token.lstrip(b"+-").lstrip(b"0") or b"0"
        limit = b"9223372036854775808" if token.startswith(b"-") else b"9223372036854775807"
        if len(digits) > len(limit) or (len(digits) == len(limit) and digits > limit):
            raise ValueError("PMU integer outside signed 64-bit range")
    try:
        with python_warnings.catch_warnings():
            python_warnings.simplefilter("error", DeprecationWarning)
            values = np.fromstring(trace, dtype=np.int64, sep=" ")
    except (ValueError, DeprecationWarning) as exc:
        raise ValueError("Malformed PMU integer token") from exc
    if np.any(np.isin(values, [5002, 6002, 5003])):
        raise ValueError("Unmatched PMU message/end delimiter")
    return values


def load_pmu(path: str, fs_default: float = 400.0) -> PMURecording:
    if not np.isfinite(fs_default) or fs_default <= 0:
        raise ValueError("fs_default must be finite and positive")
    raw = Path(path).read_bytes()
    header = re.match(
        rb"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+5002\s+LOGVERSION_(PULS|RESP)\s+(\d+)\s+6002(?!\S)",
        raw,
    )
    if not header:
        raise ValueError("Unsupported or incomplete PMU header")
    kind, version = header[5].decode().lower(), int(header[6])
    if (kind, version) not in (("puls", 1), ("resp", 1), ("resp", 3)):
        raise ValueError(f"Unsupported PMU format: {kind} v{version}")
    channels = 5 if (kind, version) == ("resp", 3) else 1
    trace = raw[header.end():]
    header_integers = [int(header[i]) for i in range(1, 5)]
    del raw, header

    # Siemens explicitly labels the later hardware region after training samples.
    training = re.search(rb"(?<!\S)5002\s+uiHwRevisionPeru(?!\S)", trace)
    discarded = 0
    if training:
        prefix = _values(_MESSAGE.sub(b" ", trace[:training.start()]))
        discarded_values = np.count_nonzero((prefix != 5000) & (prefix != 6000))
        if discarded_values % channels:
            raise ValueError("Incomplete PMU training channel group")
        discarded = int(discarded_values // channels)
        trace = trace[training.start():]
    messages = [match[1].decode("ascii") for match in _MESSAGE.finditer(trace)]
    trace = _MESSAGE.sub(b" ", trace)
    parts = re.split(rb"(?<!\S)5003(?!\S)", trace, maxsplit=1)
    end_marker_present = len(parts) == 2
    footer = _parse_footer(parts[1].decode("ascii")) if end_marker_present else {}
    values = _values(parts[0])
    del parts, trace
    marker_positions = np.flatnonzero((values == 5000) | (values == 6000))
    peak_on = values[marker_positions] == 5000
    # Marker placement refers to the current/next physical sample after removal.
    trigger_idx = ((marker_positions - np.arange(len(marker_positions))) // channels)[peak_on]
    values = np.delete(values, marker_positions)
    if not len(values) or len(values) % channels:
        raise ValueError("Empty PMU signal or incomplete channel group")
    grouped = values.reshape(-1, channels)
    signal = grouped[:, 0]
    aux = grouped[:, 1:] if channels > 1 else None
    rec = PMURecording(
        str(path), kind, version, signal, float(fs_default), trigger_idx,
        aux, messages, footer, header_integers=header_integers,
        end_marker_present=end_marker_present, training_samples_discarded=discarded,
    )
    if not end_marker_present:
        rec.warnings.append("End-of-trace marker is absent; recording completeness is unknown")
    duration = rec.footer_duration_s()
    if duration is None:
        rec.warnings.append("MDH start/stop endpoints are missing; fs uses the supplied default")
    else:
        if len(signal) < 2:
            raise ValueError("At least two samples are required for an MDH endpoint rate")
        rec.fs = (len(signal) - 1) / duration
        rec.fs_source = "mdh_endpoints"
    if discarded:
        rec.warnings.append("Samples before the explicit uiHwRevisionPeru hardware region were excluded")
    return rec


def is_flatline(sig: np.ndarray, min_unique: int = 5) -> bool:
    """Flag near-constant recorded values without inferring the sensor fault."""
    return len(np.unique(sig)) < min_unique


if __name__ == "__main__":
    import sys
    for source_path in sys.argv[1:]:
        recording = load_pmu(source_path)
        print(f"{source_path}: {recording.kind} v{recording.logversion} n={len(recording.signal)} "
              f"fs={recording.fs:g} ({recording.fs_source}) span={recording.sample_span_s:.3f}s "
              f"physiological_markers={len(recording.trigger_idx)} warnings={recording.warnings}")
