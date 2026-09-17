# uhf-fmri-qc-notes

Small research tools for the physiological side of fMRI: parse Siemens scanner physiology logs, inspect recording quality, estimate cardiac/respiratory phase and respiratory volume per time (RVT), and evaluate pulse-oximetry beat detection offline. The project grew out of practical MRI acquisition work and an interest in reliable brain-body measurements.

**Current evidence:** initial offline evaluation used three usable pulse-oximetry recordings from **two participants acquired at 3 T**, totalling approximately **209 minutes** (17,383 scanner pulse markers). These are repeated recordings, not three independent participants. Scanner pulse markers are a comparison reference, **not independent ECG ground truth**. The results do not establish clinical validity, real-time closed-loop performance, or generalisation to 5 T/9.4 T acquisitions. Raw participant logs are not included in this repository.

The `uhf` name reflects a research interest and possible future applications, not the field strength of the evaluated data.

## Implemented components

- Siemens PMU `.puls`/`.resp` parsing, including LOGVERSION 1/3, marker extraction and footer/MDH metadata.
- Recording-level QC for flat lines, clipping, long constant segments, recording-rate plausibility and missing metadata; scanner-clock alignment helpers where the required footer timestamps exist.
- Cardiac/respiratory phase and RVT estimation for physiological-noise modelling. The current CLI exports recording-level phase/RVT time series on a 1 Hz grid; it does **not** construct a complete RETROICOR design matrix sampled at fMRI volume/slice acquisition times. Acquisition-specific alignment, appropriate phase sampling and harmonic construction still require implementation and validation before downstream use.
- Offline comparison of a slope-based PPG detector with scanner pulse markers and an alternative offline detector, with reference-relative detection and timing summaries.
- Synthetic tests and fixed real-data regression cases for selected QC outputs and detector behaviour. These software checks are not independent physiological or clinical validation.

## Layout

```text
physio/
  siemens_pmu.py        PMU parser, footer/MDH metadata, pulse markers
  beats.py              PPG detection and event-matching summaries
  qc.py                 signal QC, phase/RVT estimation, log-clock offsets
  plots.py              QC and timing figures
imaging/
  qc_tsnr_motion.py     tSNR, framewise displacement and DVARS helpers
scripts/
  run_physio_qc.py      QC reports and recording-level phase/RVT export
  run_beat_eval.py      offline detector comparisons
  sim_ecg_mhd.py        illustrative synthetic ECG/MHD simulation
sessions.json           development recordings and fixed regression cases
results/                stored JSON summaries and figures
tests/                  synthetic tests and conditional real-data tests
```

The simulation is illustrative; it is not an evaluation on acquired ECG data. Imaging helpers are separate from the physiological-recording evaluation summarised below.

## Evaluation data and software regression cases

| Role | Recordings | Purpose and limitations |
|---|---|---|
| Development | S02 pre, S02 post | Two visits from one participant. PPG clipping is below 0.5%; S02 post has a recorded 17.5 s dropout. Both respiratory recordings retain QC warnings. |
| Fixed regression cases | S01 pre, S01 post | Known problematic recordings used to check that QC flags remain detectable. S01 pre has 4.5% PPG clipping; S01 post is flat-line PPG and is excluded from beat evaluation. Their respiratory logs lack footer metadata. |

The manifest covers four visits, but only three PPG recordings enter the beat-evaluation summary. The development and regression labels describe software-development roles, not independent training/test cohorts or an external validation design. Repeated visits do not increase the number of independent participants.

`tests/test_regression.py` checks expected QC verdict classes and, for the development recordings, sensitivity >= 0.99, PPV >= 0.98 and timing IQR <= 20 ms relative to scanner markers. These are regression assertions on known recordings, not general performance guarantees.

## Stored offline results

The table reproduces rounded values from [`results/beat_eval_summary.json`](results/beat_eval_summary.json). It is not a new analysis or an independently reproduced benchmark.

| Recording | Sensitivity vs markers | PPV vs markers | Median detection-minus-marker offset (ms) | Timing IQR (ms) | Timing SD (ms) | Deviations > 100 ms from median (%) |
|---|---|---|---|---|---|---|
| S02 pre (development) | 0.998 | 0.990 | -115.0 | 10.0 | 128.9 | 4.7 |
| S02 post (development) | 0.999 | 0.991 | -122.5 | 7.5 | 20.4 | 0.2 |
| S01 pre (regression) | 1.000 | 0.974 | -140.0 | 12.5 | 15.3 | 0.1 |

**Interpretation limits:**

- The metrics quantify agreement with scanner pulse markers under the repository's matching rule, not sensitivity/specificity against true ECG events. Rounded `1.000` does not imply perfect detection. Differences between scanner markers and the alternative offline detector do not by themselves identify which events are physiologically correct.
- The default scorer uses greedy one-to-one matching from 0.3 s before to 0.6 s after each reference marker. Detection and timing summaries depend on this relatively broad window; they should not be treated as precise event-timing validation. IQR, SD and the outlier fraction are shown together rather than relying on IQR alone.
- Negative offsets indicate detections earlier than the matched scanner marker. They are not end-to-end system latency, verified ECG R-peak timing, or demonstrated closed-loop timing accuracy.
- Although the code retains the function name `causal_detect`, the evaluated path calls it with `clip_pct=99.5`, calculated from the **whole recording**. The current evaluation is therefore offline, not evidence of a strictly causal streaming pipeline. Online operation would need past-data-only processing and separate acquisition-to-output timing tests.
- Phase/RVT outputs and clock-alignment helpers have not been independently validated here as a complete physiological-noise correction pipeline. Do not use the 1 Hz phase export as a drop-in fMRI RETROICOR design matrix.

## Usage

Run from the repository root:

```bash
python -m pip install -r requirements.txt
python -m pytest tests -q

# With authorised raw logs arranged as in sessions.json:
python scripts/run_physio_qc.py --data-root /path/to/logs
PHYSIO_DATA_ROOT=/path/to/logs python scripts/run_beat_eval.py S02_pre
PHYSIO_DATA_ROOT=/path/to/logs python -m pytest tests -q

# An individual recording pair:
python scripts/run_physio_qc.py --puls X.puls --resp Y.resp --out results/adhoc/qc

# Synthetic illustration only:
python scripts/sim_ecg_mhd.py --mhd 0.9
```

Raw-data-dependent tests are skipped when the required PMU logs are unavailable. A successful synthetic-test run does not reproduce the participant-level results. QC export includes JSON/PNG reports and a `*_regressors_1Hz.tsv` file containing `t_s`, `cardiac_phase`, `resp_phase` and `rvt`; the historical filename does not imply a complete fMRI-ready regressor set. Check metadata, missing values and acquisition timing before any use.

## Possible next steps

With suitable authorised data and supervision, future work could evaluate more participants, independent event references, acquisition-specific physiological modelling and prospective streaming operation. Testing at 5 T or 9.4 T would require appropriate recordings and separate validation; neither dataset availability nor comparable performance is assumed.

## Methodological background

The project applies existing signal-processing ideas; it does not claim to introduce RETROICOR or RVT. Background references retained for further reading:

- Glover, Li & Ress (2000), RETROICOR, *Magnetic Resonance in Medicine* 44:162.
- Birn et al. (2006), respiratory variation and fMRI, *NeuroImage* 31:1536.
- Kasper et al. (2017), the [PhysIO toolbox](https://github.com/ComputationalPsychiatry/PhysIO).

Research/development software. See [LICENSE](LICENSE) for the MIT licence.
