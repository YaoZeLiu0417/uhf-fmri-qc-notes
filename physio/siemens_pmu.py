"""Parser for Siemens PMU physiological logs (.puls / .resp / .ecg) as written by VB/VD/VE scanners.

Handles two layouts seen in practice:
  * LOGVERSION 1 (e.g. .puls "1 2 40 280 5002 LOGVERSION_PULS 1 6002 <samples...> 5003 <footer>")
      - one integer per sample, 400 Hz on VD/VE (50 Hz on older VB systems)
      - value 5000 = scanner-detected trigger (inserted between samples), 6000 = end-of-trigger marker
      - 5002 ... 6002 = embedded text messages
      - 5003 = end of data, followed by a footer with LogStart/StopMDHTime (ms since midnight)
  * LOGVERSION 3 with MSGTYPE 400 (e.g. .resp on VE11)
      - five integers per sample: [bellows value 0-4095, aux1, aux2, const, const]; 400 Hz
      - same 5000 trigger and 5002...6002 message conventions
      - footer may be missing if logging was not stopped cleanly

Usage:
    from physio.siemens_pmu import load_pmu
    rec = load_pmu("S01_pre.puls")
    rec.signal, rec.fs, rec.trigger_idx, rec.duration_s, rec.footer
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
import numpy as np

@dataclass
class PMURecording:
    path: str
    kind: str                      # 'puls' | 'resp' | 'ecg' | 'unknown'
    logversion: int
    signal: np.ndarray             # main channel, int
    fs: float                      # Hz (assumed 400 unless footer says otherwise)
    trigger_idx: np.ndarray        # sample indices where the scanner inserted a trigger (5000)
    aux: np.ndarray | None = None  # extra columns for 5-tuple logs
    messages: list = field(default_factory=list)
    footer: dict = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return len(self.signal) / self.fs

    @property
    def t(self) -> np.ndarray:
        return np.arange(len(self.signal)) / self.fs

    def footer_duration_s(self) -> float | None:
        a, b = self.footer.get("LogStartMDHTime"), self.footer.get("LogStopMDHTime")
        return (b - a) / 1000.0 if a is not None and b is not None else None

def _parse_footer(text: str) -> dict:
    out = {}
    for k, v in re.findall(r"(Log\w+Time):\s+(\d+)", text):
        out[k] = int(v)
    for line in text.splitlines():
        m = re.match(r"\s*(\w+)\s+(Freq Per|Min Max Avg StdDiff):\s+([\d\s]+)", line)
        if m:
            out[f"{m.group(1)}_{m.group(2).replace(' ', '')}"] = [int(x) for x in m.group(3).split()]
    return out

def load_pmu(path: str, fs_default: float = 400.0) -> PMURecording:
    text = open(path, errors="ignore").read()
    if "5003" in text[-20000:]:
        body, footer_txt = text.rsplit("5003", 1)
        footer = _parse_footer(footer_txt)
    else:
        body, footer = text, {}
    toks = body.split()
    kind = "unknown"; logversion = 1
    m = re.search(r"LOGVERSION_(\w+)\s+(\d+)", body[:400])
    if m:
        kind, logversion = m.group(1).lower(), int(m.group(2))
    # header ends after the last 6002 within the first ~60 tokens
    hdr_idx = [i for i, t in enumerate(toks[:80]) if t == "6002"]
    start = hdr_idx[-1] + 1 if hdr_idx else 4
    vals, trig, msgs = [], [], []
    skip, cur = False, []
    for t in toks[start:]:
        if t == "5002": skip, cur = True, []; continue
        if t == "6002": skip = False; msgs.append(" ".join(cur)); continue
        if skip: cur.append(t); continue
        if t == "5000": trig.append(len(vals)); continue
        if t == "6000": continue
        if t.isdigit(): vals.append(int(t))
    arr = np.asarray(vals, dtype=np.int64)
    aux = None
    if logversion >= 3 and any("MSGTYPE 400" in m_ for m_ in msgs) or (logversion >= 3 and len(arr) > 10 and arr[3] == arr[8] == 67108864):
        n = len(arr) // 5 * 5
        a = arr[:n].reshape(-1, 5)
        sig, aux = a[:, 0], a[:, 1:3]
        trig = [t_ // 5 for t_ in trig]
    else:
        sig = arr
    fs = fs_default
    fd = None
    if footer.get("LogStartMDHTime") is not None and footer.get("LogStopMDHTime") is not None:
        fd = (footer["LogStopMDHTime"] - footer["LogStartMDHTime"]) / 1000.0
        if fd > 0:
            est = len(sig) / fd
            for cand in (50.0, 100.0, 200.0, 400.0):   # snap to a plausible PMU rate
                if abs(est - cand) / cand < 0.05: fs = cand
    return PMURecording(path, kind, logversion, sig, fs, np.asarray(trig, dtype=np.int64), aux, msgs, footer)

def is_flatline(sig: np.ndarray, min_unique: int = 5) -> bool:
    """A disconnected sensor logs a constant (e.g. 2048 on PULS)."""
    return len(np.unique(sig)) < min_unique

if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        r = load_pmu(p)
        print(f"{p}: kind={r.kind} v{r.logversion} n={len(r.signal)} fs={r.fs:g} Hz dur={r.duration_s/60:.1f} min "
              f"triggers={len(r.trigger_idx)} flat={is_flatline(r.signal)} footer_dur={r.footer_duration_s()}")
