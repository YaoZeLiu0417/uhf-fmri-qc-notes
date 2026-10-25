# Automated PPG proposals for exploratory analysis

Independent manual annotation can be deferred while developing the measurement
workflow. This stage creates a separate set of **fixed-rule automated
pseudo-labels**, with AI visual screening of the 24 previously selected
disagreement windows. It does not fill the human-reference fields, train an
annotation model, or adjudicate individual events.

## Method and provenance

All 32 available cardiac exports are processed; the four absent cardiac
exports remain missing. Export hashes are checked against the prior scan-window
screen. Original samples are preserved. Each candidate retains its export
sample index, scan-relative time, parameter support and ambiguity membership.

Six related settings combine third-order, zero-phase 0.5–2/3/4 Hz bandpass
filters with peak prominence thresholds of 0.5/0.8 filtered standard deviations.
Minimum filtered-peak spacing is 0.4 s. Each peak is mapped to the highest
original sample within ±0.08 s. The central setting is 3 Hz / 0.5 SD.
One-to-one matching within ±0.10 s counts support for central candidates.
The implementation uses SciPy's [peak detection](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)
and [prominence](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.peak_prominences.html)
functions.

Six-of-six support and an original amplitude inside the ADC boundaries define
`parameter_stable`. Central candidates without that status, other settings'
unmatched candidates, and existing artifact supports mark uncertainty with a
0.20 s margin. Overlapping ranges are merged. A stable candidate outside these
marked ranges is an `exploratory_candidate`; it is not a verified pulse.
Short, nearly constant or candidate-free inputs remain unresolved.

The six settings are related transformations of the same signal, not six
independent annotators. Support is not a calibrated correctness probability.
The new candidates use neither A/B detections nor scanner markers as labels.
However, choices were made after earlier inspection of this dataset: this is
exploratory development, not preregistered or held-out evaluation. The 0.4 s
spacing, filter limits and raw-peak convention constrain the events this
method can represent. No independent accuracy claim follows from them.

## Exploratory output

| Quantity | Result |
|---|---:|
| Available / expected cardiac runs | 32 / 36 |
| Participants / visits with cardiac exports | 6 / 8 |
| Scan time with cardiac exports | 318.87 min |
| Scan time without cardiac exports | 40.93 min |
| Central candidates | 22,492 |
| Parameter-stable central candidates | 20,915 |
| Stable candidates outside marked ambiguity | 20,906 |
| Union of marked ambiguity ranges | 13.80 min |
| Export-covered windows | 646 |
| Windows with a provisional pulse-rate estimate | 559 |
| Full duration of those windows | 276.10 min |
| Median of window pulse-rate estimates | 67.22 bpm |
| Range of window pulse-rate estimates | 49.94–110.34 bpm |

The event counts are nested counts, not accuracy percentages. Marked ambiguity
is not all damaged-signal time; unmarked regions can still contain errors.
The 276.10 minutes include complete windows with local ambiguity, rather than
continuous verified measurement or interval-support time.

Pulse rate is `60 / median(retained adjacent candidate intervals)` within a
window. Both endpoints must be exploratory candidates, the interval must not
cross a marked range, and discarded central candidates are never bridged.
An estimate requires at least five retained intervals and an original
`no_rule_flag` waveform state. Original review/missing states are not relaxed.
Selection of retained intervals can bias the estimate; no ECG heart-rate,
HRV, cardiac-phase or clinical validation is established. All processing is
offline, with no acquisition-to-output timing measurement.

## Selected disagreement windows

The same 24 windows contain 734 central candidates, of which 634 survive
parameter stability and ambiguity checks. Marked uncertainty spans 50.51 s
of the selected 720 s. Prior A/B/M counts are 1,244 / 711 / 798. These are
descriptive differences, not evidence that the new method is more accurate.

AI screening inspected all six contact sheets, each with 30-second overlays
and previously selected five-second diagnostic zooms. Observations identify
small ripples, broad peaks, changing amplitude and ambiguous low-amplitude
features. No points were added/deleted, no events adjudicated, and no parameters
changed after viewing the new overlays. The other 622 export-covered windows
received automated processing only. The selected windows are still from one
participant and one visit; they are not 24 independent accuracy observations.

AI observations are stored separately from the generated proposal snapshot.
The latter correctly records that visual review was pending at generation;
the reviewed aggregate records its subsequent completion. Independent human
event annotations remain **zero**. Raw overlays, detailed event arrays,
source mappings and the Chinese review report stay private.

## Reproduction and checks

```bash
python scripts/run_provisional_ppg.py \
  --windows /private/window_qc/window_qc_details.private.json \
  --audit /private/event_audit/event_audit_details.private.json \
  --out /private/provisional_ppg

python -m pytest tests/test_provisional_ppg.py -q
```

Output must be a new directory outside the public repository and source export
directories. The CLI writes a parameter record, private proposals and overlays,
and a generation summary. AI visual review is a separate documented step;
the CLI does not automatically claim to have completed it.

Synthetic checks cover ripple-contaminated periodic input, original sample
preservation, source-index mapping, retained artifact masks, flat/unknown
signals, invalid input and refusal to bridge disputed events. The full suite
passes 67 tests and 5 subtests, with 6 legacy-path cases skipped by default.
Private readback also rehashes all 32 exports, verifies every candidate's
sample/time mapping, reconciles window partitions and aggregates, and
recomputes interval eligibility and rate estimates. These are implementation
checks, not physiological ground truth.

See the [aggregate results](../results/provisional_ppg_summary_20261025.json)
and [verification record](../results/provisional_ppg_validation_20261025.json).
Candidate retention, ambiguity distribution and parameter sensitivity can now
be studied without waiting for manual annotation. Independent references are
still needed before claiming accurate heartbeat detection or precise timing.
Task-level analysis additionally needs behavioral events and verified clock
mapping; E-Prime files are not a prerequisite for this signal-only stage.
