# Program design and presentation boundaries

Version 0.3, 26 October 2026.

The operator launcher and documentation use a black editorial field, large
light-weight typography, an asymmetric composition, cyan/magenta depth and
line-based task selection. This direction follows the user's references:
[Alto home](https://altoneuroscience.com/),
[pipeline](https://altoneuroscience.com/pipeline/),
[investors](https://investors.altoneuroscience.com/overview/default.aspx) and
[contact](https://altoneuroscience.com/contact/).
The reference pages are design sources, not scientific evidence for this task.

`ui.volume_art` generates an original projected parametric shell using depth
shading and contours. It is not an anatomical reconstruction, a measured task
manifold, participant data or a new result. No reference-site media, logo or
font is bundled. Installed Segoe UI Light / system CJK fonts are used, with
fallbacks; install a CJK font for readable Chinese on another operating system.

## Participant view

Task fields use a constant black achromatic background and a central stimulus,
following the user's selected interface direction. Stimulus luminance and
viewing geometry still need the normal site calibration.
Heartbeat and natural-respiration attention have neutral fixation, without a
visible pulse or a paced breathing animation. Visual-rhythm targets vary only
in the specified achromatic intensity. Body-feedback current/replay sources
use identical appearance and never reveal their labels to participants.

Synchrony/confidence pages belong to the body-feedback probe. Only the 1/2
panel is assumed available. Synchrony is binary (1 not synchronous / 2
synchronous), as is confidence (1 lower / 2 higher). The first valid key locks
the response without shortening the fixed page. There is no default answer
and no additional confirmation key. No press is `no_response`, not a zero
rating or an inferred inability to sense. This endpoint differs from the old
graded scales. Explicit judgeability would require an additional piloted probe.
The attention instructions and the common synchrony question require a
behavioural pilot: identical questions do not establish a successful attention
manipulation. Response periods must be handled separately in the human GLM.

The nonresponse hand carries finger PPG and the emergency squeeze bulb. It is
not used for task responses. Natural breathing is not paced; no instructed
breath holding, pulse palpation or squeeze responses are introduced. Key names
are checked in a separate operator utility. The response-box panel and actual
transport need site verification; MRI triggering remains a separate adapter.

The six-family demonstration is not a completed human protocol. GradCPT
demonstrations use abstract city/mountain shapes. Licensed photographs,
transition definitions, response windows and scoring need formal calibration.
The command-line runner accepts only `--simulate`.

## Timing and handoff

PsychoPy draws dynamic cues natively, preloads task textures and records actual
software start/end flip callbacks through `PsychoPyBlockBridge`. Flip callbacks
only enqueue receipts. GUI model events, keyboard-clock RTs, software flip
times, MRI triggers and independently measured physical output remain distinct.
The caller must reuse the same named task clock across blocks.

`present_block` can hand the accepted command's receipts to an external
controller on the same mapped clock. It does not manufacture ROI observations
or perform GP fits inside a stimulus callback. The desktop demo uses manual
synthetic selections; the separate synthetic controller runs GLM-to-GP search.

Official API references:
[Window](https://psychopy.org/api/visual/window.html),
[ImageStim](https://psychopy.org/api/visual/imagestim.html),
[Keyboard](https://psychopy.org/api/hardware/keyboard.html) and
[timing limitations](https://psychopy.org/general/timing/millisecondPrecision.html).

## Demonstration media

Screenshots and the 20-second GIF/MP4 are generated from the actual shared
renderer and `TaskPresentation` state machine with scripted synthetic actions.
Eight fps is documentation sampling, not a replay of every pulse. GIF delays
are quantized to 10 ms while preserving total duration. Hashes and parameters
are included in `assets/program/provenance.synthetic.json`.

Native PsychoPy smoke runs additionally exercise the real window and keyboard
backend using autoplay. Back-buffer captures interrupt frame performance;
they demonstrate rendered screens and task transitions, not reliable frame
timing. Site monitors, response devices, scanner triggers, physiology and
photodiode measurements remain pending.
