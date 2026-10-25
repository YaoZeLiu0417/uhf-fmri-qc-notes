# Scan-window physiological screening

This exploratory stage asks where waveform problems occur inside actual MRI
scan intervals. It uses the previously audited run onsets and sample-preserving
exports. It does not analyse brain signals, validate interoceptive perception,
or establish ECG event accuracy. Whole-record results were already known before
the fixed rules below were applied; this is not preregistered validation.

## Inputs and time accounting

There are 36 run definitions and 72 channel/run candidates. Thirty-two PPG
and 36 respiratory exports are available. The four cardiac export rejections
are retained as missing-channel intervals; missing files are not replaced
with artificial physiological samples. An unavailable input root raises an
error instead of being treated as missing channel data.

Each run is divided into `[0,30)`, `[30,60)`, and subsequent 30-second windows,
with the final partial window retained. Durations, rather than window counts,
are summed. The 1,458 planned channel/windows include 83 missing cardiac
windows; 1,375 contain exported measurements. The target duration is 359.8
minutes per channel. Two channels must not be added as independent scan time.

Samples are assigned by their timestamps in the half-open scan interval.
Coverage is bounded by the original array's first and last sample times.
Constant-sequence spans use `(N - 1) / fs`; sample-support duration is a
separate field. The array's last sample is not extended beyond its timestamp.
Existing pre/post scan samples provide the necessary coverage in this batch.

## Fixed descriptive rules

| Condition | Output |
|---|---|
| No samples, no finite samples, or fewer than five distinct finite values | `unusable` / insufficient for this screen |
| ADC boundary values (`<=0` or `>=4095`) exceed 1% of finite window samples | `review` |
| A constant sequence touching the window has a first-to-last span greater than 5 s | `review` |
| Nonfinite values, values outside the declared ADC range, or incomplete coverage | Additional review reason |
| No implemented rule fires | `no_rule_flag`, not validated usable time |
| Channel export absent | `missing` |

The comparisons are strictly greater than 1% and 5 s. Constant sequences are
found across the entire run before assignment to windows, so a six-second
plateau crossing a window boundary is not split into two harmless three-second
segments. Separate interval records retain all ADC-boundary samples even when
their windows stay below the 1% threshold. Flag categories may overlap; their
total sample-support duration is the union, not the sum of category durations.

These are software review rules inherited from the existing recording-level
screen, not clinically validated acceptance thresholds. A flag on a 30-second
window does not mean all 30 seconds are corrupted. Gain-message timestamps
are not available in the exports, so this stage does not infer exact gain
transition times or certify respiratory amplitudes.

## Results

| Channel | Present runs | No rule flag | Review | Missing export | Flagged support union |
|---|---:|---:|---:|---:|---:|
| PPG | 32 / 36 | 276.20 min | 42.67 min | 40.93 min | 2.86 min |
| Respiration | 36 / 36 | 175.27 min | 184.53 min | 0.00 min | 10.00 min |

No exported window met the insufficient-variation `unusable` rule. This does
not mean all exported windows are fit for a particular physiological measure.
PPG has 86 review windows, all with ADC-boundary fraction above 1%.
Respiration has 372 review windows; all exceed the ADC-boundary threshold,
and four also touch constant spans longer than five seconds. The latter four
must not be counted a second time in the review-duration total.

The longest run-internal constant spans are 1.355 s for PPG and 6.205 s for
respiration. Whole-log extremes of approximately 361 and 256 s therefore
cannot be used as the duration of failure within these exported scan windows.

## Event-count disagreement as a separate review clue

The existing slope detector and alternate bandpass peak detector run once
per padded PPG scan export, using unchanged parameters and the same sample-
hold preprocessing. Window counts are then assigned from the resulting event
times. The detectors are not reinitialised every 30 seconds.

The descriptive count difference is `abs(A - B) / max(A, B)`. It exceeds 20%
in 27 full 30-second windows, each with at least ten events from each detector.
Twenty-four of these windows have `no_rule_flag` under the waveform checks.
This count difference is not an event-matching metric, does not establish
which detector is correct, and does not enter the primary waveform-QC gate.
Equal counts would not prove correct event timing either.

Private examples are chosen using rules recorded in the aggregate JSON:
a low-clipping, similar-count candidate; the greatest clipping fraction;
and the greatest count difference among minimally clipped rule-unflagged
candidates. A missing category is recorded rather than replaced with a
mislabelled example. The selected disagreement example has 63 versus 23
events with zero ADC-boundary samples, illustrating a limitation of gross
waveform rules. The candidate examples are not a random validation sample
and are not uploaded to this repository.

## Reproduce

The private run manifest uses `run_id` and `duration_seconds` from the
[run example](../examples/runs.example.json). The physiological export root
must already exist and contain the corresponding TSV.GZ/JSON files.

```bash
python scripts/run_window_qc.py --manifest /private/runs.json \
  --physio-root /private/exported_physio --out /private/window_qc
```

Outputs include a rules record, private run/window and interval details,
an aggregate JSON and chart, and private candidate waveform plots when all
three categories are available. The CLI refuses output within the repository
or source physiology root and refuses overwriting existing result files.
Only reviewed aggregate files should be copied into a public release.

The local review workbook has blank human-assessment fields. Human window
adjudication, independent event annotation and E-Prime clock/trigger mapping
remain pending. The next measurement question is whether a trial lies inside
a reviewed interval and whether the chosen pulse-event definition is reliable
enough for that trial's intended use.
