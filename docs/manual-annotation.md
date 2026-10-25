# Raw-only PPG annotation preparation

The local event audit found two distinct measurement issues: unavailable
cardiac scan exports from a short constant source, and 24 waveform-unflagged
windows whose event candidates disagree. The latter windows are the input to
this annotation preparation step. The public project does not include their
raw waveforms or participant mapping.

## What the page does

`build_ppg_annotation.py` produces a self-contained, offline page from the
previously checked scan exports. It preserves every original ADC sample in
the selected windows, including the actual first-sample offset. There are no
algorithm event locations, counts or study identifiers in the viewing data.
Case identifiers are linked to source scans in a separate private mapping.

The reviewer records their identifier, date, intended waveform fiducial and
definition, and prior exposure to algorithm results. This is a raw-only view;
it cannot establish that a reviewer has never seen the previous results.
Metadata are attached to each case and locked after annotation begins.

The page supports 30-, 10-, 5- and 1-second views, panning, manual event
points, uncertain intervals, deletion and undo. Event clicks snap only to the
nearest original sample timestamp, not to computed peaks. A window cannot be
recorded complete with unresolved point/uncertainty conflicts. A window with
no confident events must be represented as entirely uncertain rather than
silently labelled as containing zero pulses.

Browser storage is temporary convenience, not a backup. Exported JSON binds
annotations to a dataset fingerprint and includes both sample indices and
window-relative event times. Import checks that fingerprint, case coverage,
index ordering, ranges, metadata, and agreement between indices and timestamps.
Unreviewed windows keep a null event-time list. Importing another dataset is
rejected before the current annotations are replaced.

## Build and use

```bash
python scripts/build_ppg_annotation.py \
  --audit /private/event_audit/event_audit_details.private.json \
  --windows /private/window_qc/window_qc_details.private.json \
  --out /private/event_annotation
```

Open the resulting `PPG原始波形标注.private.html` in a local browser. Enter
the intended event definition before marking points, use uncertain intervals
for ambiguous waveform regions, record the case, and export the JSON after
each session. The private `case_mapping.private.json` joins case identifiers
to the source run, window and existing review-workbook row.

Use a consistent fiducial definition for a review round. PPG waveform
annotations can support event-recognition checks but are not independent ECG
R-peak or hardware latency validation. The selected disagreement windows are
not a random or independent population accuracy sample. At delivery, all
24 cases remain unannotated; interface test inputs are not human reference
labels, and no prior workbook human-assessment cells were filled.

## Checks

Python builder tests verify exact sample preservation, identity hiding,
refusal of changed inputs, and rejection of unsafe case identifiers.

```bash
python -m pytest tests/test_annotation_builder.py -q
node tests/test_annotation_core.cjs
```

Core checks cover sample-time mapping, unknown-versus-zero labels, completion
rules, uncertain intervals, import/export and invalid inputs. A local Chrome
test also exercised adding/deleting points, undo, window navigation, reload
persistence, JSON export/import, wrong-fingerprint rejection, and desktop and
mobile layout. The browser tests used explicitly labelled interface-test
inputs in isolated browser contexts, not independent human annotations.
