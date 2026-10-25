# MRI–physiology progress and analysis readiness

Status checked on 25 October 2026. This note reports aggregate progress from a
companion local workflow. Participant-level files, scan dates, clinical results,
identity mappings and raw waveforms are not included. The local conversion and
analysis scripts are not bundled in this public repository.

## Evidence levels

| Level | Current scope | What it establishes |
|---|---|---|
| Archived source data | 6 participants, 9 visits, 18 PMU files | Traceable recording inventory; repeated visits are not new participants |
| Recording coverage | 8 long, nonconstant PPG recordings; 9 respiratory recordings | Approximately 621.1 PPG and 711.7 respiratory minutes recorded; not all minutes are valid for event detection |
| Curated MRI | 36 BOLD runs: 19 rest, 8 ER and 9 IA | Available acquisition inventory, not 36 independent observations |
| Run-specific physiology | 68 exports: 32 cardiac PPG and 36 respiratory | 32 BOLD runs have both channels; 4 have respiration only |
| Preprocessed resting MRI | 3 paired participants, 6 visits, 13 runs | Output completeness checked; comprehensive manual image QC remains distinct |
| Current MRI-only paired FC analysis | 2 participants | Exploratory analysis after the existing motion/data-retention gates |
| Detailed resting waveform/timing audit | 24 exports: 13 respiratory and 11 PPG | Window-level QC and timing checks within the processed subset |
| Current paired rate–BOLD analysis | 0 eligible pre/post pairs | No paired brain–physiology effect established under the existing numerical gates and waveform review |
| Historical detector benchmark | 2 participants, 3 PPG recordings, about 209 minutes | Stored marker-relative performance only; not rerun on the expanded archive |

One visit's PPG log is only approximately 9.53 seconds, constant, and outside
the functional scans. Its four curated BOLD runs therefore have no cardiac
export. No replacement recording or imputed heartbeat series was substituted.

The original acquisition inventory contained 39 functional series; after
recorded duplicate/failed-series selections, the curated dataset contains 36.
Run numbering alone does not identify matching acquisition conditions across
visits: source protocols and repeated acquisitions must also be checked.

## Completed local work

The local workflow separates physical channels in Siemens PMU logs, excludes
embedded messages and physiological peak markers from the sample stream,
estimates effective storage rates from scanner-clock endpoints, and exports
per-run BIDS TSV.GZ/JSON with `SamplingFrequency`, `StartTime` and `Columns`.
The PPG channel is labelled cardiac, not ECG or beats per minute.

Acquisition-time audits found that the first stored DICOM slice need not be
the earliest slice in a volume. In an audited example, treating that file's
time as volume onset introduced a 1.485-second offset. The local conversion
workflow derives volume onset and slice order from source timestamps and
geometry, checking consecutive volumes before writing derived metadata.
This is an identified timing-reference correction, not independent proof of
sub-second synchronization accuracy.

The existing processed-subset audit also checked the executed cortical
slice-time reference: 0.949 seconds after each TR onset. That reference must
not automatically be extended to subcortical data or an entire mixed CIFTI.

### Verification performed for this update

- All 18 archived source copies match the recorded SHA-256 and byte counts.
  Six still-accessible original files were also compared with those copies.
  The original drive for the other twelve files was unavailable during this
  check; their historical copy records and current archived copies were checked.
- All 68 exported files were freshly decompressed and checked for finite,
  one-column data, sample counts, sidecar consistency, nonconstant signal and
  time coverage against the actual BOLD NIfTI header duration.
- Gross waveform checks were recomputed over all 68 curated run/channel
  exports. This completes that limited check across the expanded archive;
  detailed peak detection, window validity and brain–physiology eligibility
  were not rerun beyond the already analysed resting subset.

These checks establish file integrity and traceability. Clipping, ambiguous
peaks and intermittent unreliable segments can remain in a file that passes.

## Why paired brain–physiology results are still unavailable

The existing analysis intersects valid physiological samples with the same
motion/nonsteady-state mask used for MRI. Its fixed numerical gates require
at least 80% valid physiological windows, 150 jointly valid frames, 50% of the
original frames and no internal common-data gap longer than 30 seconds.
These are technical criteria for this exploratory analysis, not clinically
validated universal signal-quality thresholds.

No pre/post pair passes the current requirements. A single post-visit PPG
run is numerically computable, but manual review identified peak ambiguity,
so it does not establish a physiologically valid brain–heart association.
The result does not mean every recording in the expanded archive is unusable:
the detailed paired analysis concerns the currently processed subset.

Existing MRI-only results and global-signal-regression sensitivity analyses
do not demonstrate that peripheral physiological influences have been
removed. GSR is not a substitute for measured respiratory/cardiac modelling,
and a reduction after regression does not identify the removed component's
neural or vascular origin.

## Remaining timing and measurement limits

Synchronization uses MDH start/stop endpoints and a uniform-sampling model.
Effective rates near 400 Hz are estimates, not independently verified hardware
rates. There is no verified volume-TTL sequence or per-sample clock reference;
within-recording dropout, jitter and nonlinear drift remain unresolved.
Physiological markers 5000/6000 must not be treated as verified MRI TTL.

The respiratory belt is uncalibrated and includes gain changes. Its amplitude
is not a direct cross-visit ventilation measure, and it does not measure
end-tidal CO2. PPG peaks are not ECG R waves. Neither the legacy 1 Hz phase
export nor the local raw BIDS export is a validated RETROICOR design matrix.

## Next analysis

1. Extend the existing window-level waveform protocol to additional visits,
   record all failures and manually review representative peak detections.
   Keep physiology-only feasibility separate from paired MRI inference.
2. Join waveform quality to imaging motion, retained original time indices,
   source protocol and the verified processing reference. Select technically
   usable runs before estimating associations; preserve the current gates.
3. On eligible data, compare a fixed baseline model with measured slow
   respiratory/pulse-rate terms using identical time masks and stated lags.
   Report every prespecified comparison rather than selecting the best lag.
   Rate-only models do not constitute complete physiological correction.
4. Use full archived logs when response functions need more context than the
   exported approximately five-second margins, or explicitly exclude edges.
   Validate phase/event timing separately before using phase-based models.
5. Keep GSR as a separate sensitivity branch. Assess effect sizes, uncertainty
   and repeatability; residual variance reduction alone is not evidence of
   improved neural specificity. ER/IA task analysis also needs verified event
   timing and suitable preprocessed task data.

### Historical QC provenance correction

Old stored respiratory QC for two visits reported missing footers. The current
complete files contain all MDH/MPCU endpoints, and the legacy footer check
recognises them. The old reports describe shorter recordings and lack
input hashes, so input equivalence and the cause of the discrepancy remain
unresolved. Keep the old results as historical artifacts; do not describe
those warnings as confirmed failures of the current complete recordings.
