# MRI physiological measurement progress — October 2026

Updated 25 October 2026. PMU parsing, recording QC, offline pulse-event
comparison, acquisition-window export and aggregate reporting are now
integrated into this repository. Raw paths, participant identifiers, actual
acquisition clocks and waveforms remain private.

## Evidence now available

| Level | Scope | Interpretation |
|---|---|---|
| Recording inventory | 6 participants, 9 visits, 18 original logs at 3 T | Visits remain nested within participants |
| Long, nonconstant PPG | 8 records; 621.135 recorded minutes | Includes non-scan periods and low-quality segments |
| Respiration | 9 records; 711.678 recorded minutes | Whole-record duration, not accepted measurement time |
| Recording-level QC | PPG: 4 OK / 4 WARN / 1 FAIL; respiration: 0 OK / 9 WARN / 0 FAIL | Coarse checks, not event-level validity |
| Offline pulse comparison | 8 records from 6 participants | Agreement with scanner pulse markers under stated windows |
| Acquisition-window export | 36 run definitions; 72 channel/run candidates | Onsets supplied by an external audit |
| Accepted exports | 32 cardiac PPG + 36 respiratory = 68 | Source samples and relative timing retained |
| Refused exports | 4 cardiac candidates from one failed short record | No replacement signals or synthetic pulses |

The failed PPG source is approximately 9.53 seconds long, constant and outside
its target acquisitions. The longest constant intervals in the complete logs
are 360.8 seconds for PPG and 255.6 seconds for respiration. Respiratory logs
also contain gain messages; arbitrary-unit amplitude is not calibrated
ventilation.

Respiratory QC now warns on a constant interval longer than five seconds.
This changes the previous tally from 1 OK / 8 WARN to 0 OK / 9 WARN without
changing samples or other reported measurements.

## Integration and verification

The parser separates LOGVERSION 1/3 sample streams, messages and physiological
markers while retaining event indices in the original sample coordinate
system. The detector's trailing average now preserves the original sample
count and indexing. Detector parameters were not retuned for the expanded
evaluation.

The exporter calculates effective frequency as
`(number of source samples - 1) / MDH endpoint duration`. It uses an externally
audited stored-volume onset, preserves separate channel offsets and retains
up to five seconds of existing context around each run. Missing clocks,
inadequate coverage and constant signal within the strict `[start, stop)`
interval are refused. No interpolation or invented padding is applied.

An independent comparison read all **68 new and 68 existing TSV.GZ files**.
Their **16,560,242 samples matched exactly**, as did the decompressed text.
`SamplingFrequency`, `StartTime`, `Columns`, `PhysioType` and units also
matched exactly. Revised metadata states timing assumptions, omits original
source names and absolute clocks, and records relative source slice indices.
The stricter flatline boundary check changes none of the 68 acceptance
decisions, so another full export was unnecessary.

These checks establish reproducible sample extraction. They do not establish
that every exported second is suitable for physiological measurement.
Synthetic tests cover event indices, matching counts, undefined denominators,
clock parsing, output refusal, deterministic compression and fractional
acquisition boundaries.

## Expanded offline pulse comparison

Two windows chosen before the expanded run score the same 41,523 reference
pulse markers and 42,804 detections:

| Matching window relative to marker | Matched pairs | Pooled marker recall | Pooled detection PPV |
|---|---:|---:|---:|
| -0.30 to +0.60 s | 41,247 | 99.3353% | 96.3625% |
| -0.15 to +0.30 s | 34,056 | 82.0172% | 79.5627% |

These are pooled event ratios, not independent participant observations or
an independent test cohort. Per-record wide-window PPV spans 81.17–99.55%;
median detection-minus-marker offsets span approximately -145 to -120 ms.
A coarse QC pass does not guarantee reliable individual events.

The narrower window's left boundary is near those systematic offsets.
Reduced agreement shows dependence on the matching rule, not an established
physiological miss rate. Scanner markers are not independent ECG truth.
Timing IQR, standard deviation and outlier summaries should be read together.

Despite the retained name `causal_detect`, the evaluated path computes a
percentile cap from the whole recording. It is offline. Marker-relative
offsets are neither ECG R-peak errors nor measured end-to-end latency, and
closed-loop performance has not been established.

## Timing and provenance limits

A local source-metadata audit found a 1.485-second difference between the
first stored slice's timestamp and the earliest slice in its volume. The
public exporter accepts an independently audited onset; it does not provide
automatic DICOM reconstruction or infer MRI TTL from physiological markers.

MDH endpoints estimate effective sample spacing under uniform sampling.
They do not independently verify hardware frequency or exclude intermediate
dropouts, jitter and nonlinear drift. A successful export verifies extraction
under the supplied timing model, not absolute synchronization accuracy.

Trial-level stimulus/response alignment awaits task event logs and verified
clock/trigger mapping. E-Prime timestamps alone do not prove a shared time
base; the present measurement work does not depend on that pending handoff.

The original benchmark of approximately 209 minutes, three PPG recordings
and two participants remains unchanged. Old respiratory reports lack input
hashes, describe shorter inputs and reported missing footers. Current
complete sources contain all clock endpoints. The cause of that discrepancy
is unresolved and should not be described as a confirmed acquisition fault.

The evaluated data are **3 T**, despite the repository's `uhf` name.
UHF performance and interoceptive perception remain unvalidated.

## Reproduction and next measurements

Use the [cohort example](../examples/cohort.example.json) for one row per visit,
and the [run example](../examples/runs.example.json) for externally audited
acquisition windows. Both contain fictional identifiers, paths and clocks.
Keep actual manifests and detailed outputs private.

~~~bash
python scripts/evaluate_cohort.py --manifest COHORT.private.json --out OUTPUT/measurement_summary.json --details OUTPUT/measurement_details.private.json
python scripts/export_bids_physio.py --manifest RUNS.private.json --out OUTPUT/bids_physio --report OUTPUT/export_report.private.json
~~~

1. Establish valid segment duration within each audited acquisition,
   documenting clipping, flat intervals, ambiguous events and exclusions.
   Report accepted time separately from complete log duration.
2. Add independent event annotation and suitable reference measurements,
   preserving adjudication rules and uncertainty around ambiguous events.
3. Validate prospective streaming with past-data-only processing and measured
   acquisition-to-output timing before any closed-loop claim.

Aggregate artifacts: [measurements](../results/measurement_summary_20261025.json),
[figure](../results/measurement_summary_20261025.png),
[validation](../results/measurement_validation_20261025.json), and
[progress inventory](../results/progress_summary_20261025.json).
