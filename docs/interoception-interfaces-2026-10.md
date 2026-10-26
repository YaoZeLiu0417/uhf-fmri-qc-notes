# Neuroadaptive interoception interface contract

Version 0.2. The prototype computes a real GP and acquisition function from
incremental ROI GLM estimates. It emits recommendations to an external task
presenter. It does not acquire MRI/physiology, register masks or authorize
human acquisition. Read the [scientific plan](interoception-protocol-2026-10.zh-CN.md)
and [method comparison](romy-replication-map-2026-10.zh-CN.md).

The v0.3 native presentation layer is documented in
[program design](program-design-2026-10.md). The desktop demo uses synthetic
manual selections; it does not imply that ROI streaming or online optimization
has been connected to the hospital scanner. `present_block` forwards actual
software start/end receipts through the existing bridge on a shared clock.

## Task space and ROI inputs

The synthetic registry has 18 candidate presets in six proposed families.
Its coordinates are artificial. The site template deliberately leaves the
independent embedding, normalization, ROI and calibration definitions empty.
Numeric task IDs are not distances. Fixed toy hyperparameters are not site
estimates or exact original-paper values.

The initial target is candidate `beta_III - beta_IV` in common PSC units.
Current-minus-replay and attention-by-contingency are different objectives
requiring complete matched groups. Uneven III>IV sampling cannot identify the
opposite optimum. Explicitly reverse the target in a separate search.

`roi_input.extract_roi_input(volume, iii_masks, iv_masks, baseline=..., space_id=...)`
requires a 3D image and masks already on the same grid. It checks shape,
affine, nonzero labels, finite data and empty/overlapping regions. Original
III/IV masks have labels 3/4, not 1. Same-region hemisphere masks can be unioned.
No registration/resampling occurs. An independent frozen baseline declaration
and means are mandatory; their provenance cannot be proven from two numbers.
Return values include raw means, PSC, counts and source/definition hashes, not
image arrays or identity paths. Unknown header units stay unknown.

## Causal JSONL messages

Times are finite seconds on a mapped task-monotonic clock. Preserve original
device clocks and calibrated transforms privately. A label does not establish
synchronization. Acquisition, availability, software callback, physical output
and scanner-trigger times remain distinct.

| kind | Payload | Effect |
|---|---|---|
| request_next | now_s | Wait or recommend a registered condition |
| block_started | Original command, onset_s, planned duration_s | Register actual start and provisional boxcar |
| block_ended | block_id, actual offset_s | Replace planned duration with actual duration |
| roi_volume | volume_id, sample_time_s, roi_values, available_time_s, clock_id, roi_definition_id, is_synthetic, valid, optional motion | Append the paired ROI values, never a raw image |
| readouts | now_s | Refit available data and report eligible block estimates |
| freeze | now_s | Lock training snapshot/optimizer and create a new test GLM |

A new task cannot be recommended while the previous command is unstarted,
before actual end, or before an eligible GLM estimate. Inputs must match the
run, condition, clock, ROI and provenance. Invalid messages produce rejection,
not another task. Site adapters still need timeouts, aborts, stream-loss and
operator recovery rules. This bridge is not a production failure controller.

`stream_controller --input-jsonl -` reads stdin and flushes one JSON response
per event. A path replays messages in arrival order. Logs stay private.
Neither mode opens device ports or presents stimuli.

## GLM and GP updates

The GLM uses actual block boxcars convolved with a double-gamma HRF, intercept,
drift and optional six motion terms. It only uses volumes available by scoring
time, excludes invalid samples, and checks rank and residual degrees of
freedom. The full 32-second tail is a conservative prototype wait, not Lorenz's
exact update timing. Each update re-estimates historical betas. GP fit therefore
replaces the complete observation snapshot; a re-estimated old block is not
another observation. Separate blocks at one condition remain repeats.

The controller uses the fixed configured GP noise, not unwhitened OLS variance
as a certainty estimate. Within-GLM beta covariance and BOLD autocorrelation
remain limits. The zero-mean GP uses squared-exponential covariance. Standard
EI uses posterior SD. Configurable fixed-weight GP-UCB is a prototype variant,
not the 2021 paper's full time-varying exploration rule. Every decision records
all candidate means, SDs, acquisition scores and its reason.

## PsychoPy handoff

PsychoPyBlockBridge validates registry, run, definition, role and clock before
queuing Window.callOnFlip start/end callbacks. The clock is read only when
the callback executes. Start duration is planned; end provides actual software
offset. Physical trigger/output timestamps remain null until independently
measured. The event sink only enqueues. Drain serially outside the callback;
do not run GLMs, GP fits, network calls or disk flushes there.

Tests use fake windows. Physical PsychoPy timing has not been validated. The
six proposed families still need complete, piloted task presenters.

## Freeze and validation

New search runs rebuild the GLM and reset GP. Freeze retains the training
snapshot and posterior. The optimizer refuses further fit/suggest. The fixed
test plan uses a new GLM: test volumes never refit training beta estimates or
update the GP, even indirectly. Reinitializing another adaptive search is a
separate reliability check.

## Body-feedback submodule

The earlier CueScheduler and plan_replay remain for the four-condition probe.
Event occurrence, availability and output deadline differ. Late/ambiguous
pulses are skipped with a reason; synthetic physiology cannot replace missing
live input. Replay offsets come from an independently prepared episode while
current physiology continues to be recorded. Requests differ from receipts.
The older simulate module uses a balanced fallback, not the new GP path.

Fill [site_profile.template.json](../experiments/interoception/site_profile.template.json)
privately. Official masks remain in the author's repository, outside this MIT
package. Human data are never part of the synthetic example.
