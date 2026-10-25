# Selected-window PPG event audit

This stage follows the fixed scan-window screen. It examines every cardiac
window labelled `no_rule_flag` whose two detector event counts differ by more
than 20%. The 24 selected 30-second windows span 12 minutes from one
participant, one visit, three runs and one source pulse recording. Selection
was conditioned on disagreement, so the results cannot estimate population
accuracy or be treated as 24 independent observations.

## Event definitions and provenance

| Event source | Operational meaning |
|---|---|
| A: existing slope detector | Local response in the trailing-smoothed slope, with adaptive threshold and refractory period; includes a whole-input percentile cap |
| B: existing alternate detector | Peaks after zero-phase 0.5–8 Hz filtering, with spacing and prominence constraints |
| M: scanner physiology | `5000` physiological markers in the same source PULS recording; firmware-defined comparison events |

These definitions do not establish a common physiological fiducial, an ECG
R-peak, or system latency. PPG detectors can target different waveform features,
including peaks and systolic upslopes; see the primary benchmark by
[Charlton et al. (2022)](https://doi.org/10.1088/1361-6579/ac826d).

Each exported waveform was required to match the exact source slice indicated
by `SourceSliceStart`/`SourceSliceStop`. The source hash matched the archived
copy record. Marker indices were transformed through that same slice and
the export's effective sampling frequency. The MDH endpoint and externally
audited run-onset mapping were also checked. Their zero internal discrepancy
is a consistency check under the existing timing model, not independent TTL
or hardware synchronization validation.

Detector parameters were unchanged. A and B were recomputed on each complete
padded run, reproducing all 24 stage-1 window counts. The same detectors were
also applied to the complete source log to describe context sensitivity.
No fixed event-time shift was estimated or applied.

## Pairing and window boundaries

The legacy one-to-one, earliest-available matching window is retained:
`[marker - 0.3 s, marker + 0.6 s]`. Pairing takes place across the run before
events are assigned to display windows. A pair can cross a window boundary;
reference-side and detection-side matched counts therefore use separate
window membership and denominators. An unmatched detection is not labelled
a true physiological false positive.

Timing distributions include matched events only. Broad greedy pairing,
ambiguous references and selection can affect which events are paired; these
offsets are not an independent measure of event-time error.

## Results and interpretation

| Source | Candidate events in the selected 12 minutes |
|---|---:|
| A | 1,244 |
| B | 711 |
| M | 798 |

A has more events than M in 23 of 24 windows. AI-assisted inspection of the
full-window and diagnostic-zoom plots shows additional A responses at small
fluctuations, shoulders and descending portions of larger waves. Some windows
also have M markers at differing waveform locations and substantial B/M
disagreement. These are initial visual clues requiring independent event
adjudication, not verified missed/extra heartbeats or a diagnosis.

The per-window median detection-minus-marker offsets range from approximately
−187.5 to +297.5 ms for A and −50.0 to +287.5 ms for B under the retained
matcher. Their changing signs and count differences do not support treating
this subset as a single constant-lag problem.

Whole-record versus run-local processing changes event counts in seven of
the selected windows for each detector, by at most five events for A and
six for B per window. The large cross-detector disagreement remains present.
Both processing paths are offline; input-dependent global statistics and
adaptive/filter context can influence outputs.

The selected windows remain unresolved for precise pulse-event counting and
timing. They are not automatically declared unusable for every possible
physiological measure, and other unreviewed windows are not thereby certified.

## Review material and next reference

Private review material contains 24 case records and six pages of complete
30-second waveform overlays with five-second zooms. The zoom is the first
five-second subwindow maximising the A/B count difference, used for diagnosis
rather than random sampling. Separate full-window raw pages hide the detector
locations and counts. An empty annotation template preserves the distinction
between unlabelled and zero-event windows.

Independent reviewers should first define the intended PPG fiducial, inspect
raw pages before algorithm overlays, and retain uncertain intervals. Such
annotations can assess waveform-event recognition but do not independently
validate ECG R-peaks. Existing review-workbook human fields remain untouched;
AI-assisted observations are not entered as human acceptance. New independent
data are needed for external validation after algorithm development.

```bash
python scripts/audit_event_disagreements.py \
  --windows /private/window_qc/window_qc_details.private.json \
  --runs /private/runs.json --out /private/event_audit
```

The run manifest is the same audited input used for export. The CLI writes
private cases and overlay pages plus an aggregate JSON and consistency checks.
Output inside the repository, source export directory or raw source directory
is refused. Raw data and prior outputs are not overwritten. The public figure
and aggregate validation record were assembled from the saved outputs; private
waveforms and case identifiers are not included in this repository.
