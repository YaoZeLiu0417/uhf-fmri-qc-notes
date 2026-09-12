# uhf-fmri-qc-notes

Small, tested tools for the physiological side of (ultra-high-field) fMRI: parse scanner physiology logs, detect heartbeats
causally the way a closed-loop paradigm would, run operator-level QC, and produce RETROICOR/RVT nuisance regressors
aligned to the scanner clock. Written while preparing for layer-fMRI work on interoception and cognitive control.

Validated on three clinical fMRI sessions from two participants acquired at 3 T (Siemens) at Tsinghua (209 min of pulse
oximetry, 17,383 scanner pulse triggers). The physiology side is field-strength independent; the 3 T sessions are the
baseline against which 5 T (United Imaging) and 9.4 T recordings will be compared. Raw logs are not part of this repository.

## Layout

```
physio/            library
  siemens_pmu.py   Siemens PMU .puls/.resp parser (LOGVERSION 1 and 3), footer/MDH clock, trigger markers
  beats.py         causal beat detector, offline reference detector, sensitivity/PPV/latency/jitter scorer
  qc.py            flat-line / clipping / dropout / footer / rate checks; RETROICOR phases; RVT; puls–resp alignment
  plots.py         figures
imaging/
  qc_tsnr_motion.py  tSNR map, framewise displacement and DVARS for an EPI run (nibabel)
scripts/
  run_physio_qc.py   QC + regressors for one or all sessions listed in sessions.json
  run_beat_eval.py   causal detector vs scanner triggers, per session, with summary
  sim_ecg_mhd.py     why amplitude ECG triggering fails in the magnet (simulated MHD-elevated T wave)
tests/               pytest: synthetic tests always run; real-data tests run when the logs are present
sessions.json        manifest: which recordings are development data and which are fixed regression cases
results/             JSON metrics and PNG figures per session (regressors .tsv are ignored by git)
```

## Development vs regression data

| Role | Sessions | Why |
|---|---|---|
| dev | S02 pre, S02 post | complete logs with footers (alignable to DICOM time), <0.5 % PPG clipping, two sessions of one participant for repeatability |
| regression | S01 pre, S01 post | known acquisition faults the QC must keep flagging: 4.5 % PPG clipping, flat-line pulse sensor, respiration logs not stopped cleanly |

`tests/test_regression.py` asserts each session keeps its verdict class (OK / WARN / FAIL) and that the dev sessions keep
sensitivity ≥ 0.99, PPV ≥ 0.98, jitter IQR ≤ 20 ms against the scanner's own triggers.

## Results on the three usable pulse recordings

| Session | Sensitivity | PPV | Median lead vs scanner trigger | Jitter (IQR) | Outliers > 100 ms |
|---|---|---|---|---|---|
| S02 pre (dev) | 0.998 | 0.990 | 115 ms | 10.0 ms | 4.7 % |
| S02 post (dev) | 0.999 | 0.991 | 122 ms | 7.5 ms | 0.2 % |
| S01 pre (regression) | 1.000 | 0.974 | 140 ms | 12.5 ms | 0.1 % |

The causal detector fires on the PPG upslope, i.e. before the scanner's own trigger; the scanner trigger itself misses
0.4–2.6 % of beats found offline. Jitter is reported as IQR because a few mis-pairings at ~93 bpm inflate the SD
(129 ms on S02 pre) while the IQR stays at 10 ms.

## Usage

```bash
python scripts/run_physio_qc.py                # all sessions; writes results/<role>/<session>/qc.{json,png,_regressors_1Hz.tsv}
python scripts/run_beat_eval.py S02_pre    # one session
python scripts/run_physio_qc.py --puls X.puls --resp Y.resp --out results/adhoc/name
python scripts/sim_ecg_mhd.py --mhd 0.9
PHYSIO_DATA_ROOT=/path/to/logs python -m pytest tests -q
```

Requirements: `pip install -r requirements.txt` (numpy, scipy, matplotlib; nibabel for `imaging/`, pydicom for `scripts/dicom_run_times.py`, pytest for tests). MIT license.

## Why pulse oximetry and not ECG

In the magnet, blood flow in the aorta induces a magnetohydrodynamic (MHD) voltage that elevates the T wave and grows
with field strength; at 7 T it substantially degrades ECG-based triggering (Krug et al., [PMC6024401](https://pmc.ncbi.nlm.nih.gov/articles/PMC6024401/)).
Pulse oximetry, acoustic triggering ([Frauenrath et al. 2010](https://jcmr-online.biomedcentral.com/articles/10.1186/1532-429X-12-67))
and electrode-free pilot-tone/beat-sensor methods are the ultra-high-field alternatives. The pulse signal lags the R wave
by the pulse arrival time (~200–300 ms at the finger, [PMC6912522](https://pmc.ncbi.nlm.nih.gov/articles/PMC6912522/)),
so any interoception paradigm timed to PPG must model that delay explicitly.

References: Glover, Li & Ress (2000) RETROICOR, Magn Reson Med 44:162; Birn et al. (2006) RVT, NeuroImage 31:1536;
Kasper et al. (2017) PhysIO toolbox, [github.com/ComputationalPsychiatry/PhysIO](https://github.com/ComputationalPsychiatry/PhysIO).
