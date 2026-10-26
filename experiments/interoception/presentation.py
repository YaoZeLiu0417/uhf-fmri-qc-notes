"""Dependency-free participant flow, not a validated task or hardware clock.

``advance`` consumes caller-clock inputs; ``view`` never changes state. Events
are software model events. Use psychopy_bridge for actual flip callbacks and
independent output measurements for physical timing. Demo defaults, synthetic
rhythms and geometric GradCPT placeholders are never used in real mode.
"""
from copy import deepcopy
import math
from pathlib import Path
import random


FAMILIES = {
    'heartbeat_attention': ('心跳注意', '关注自己的心跳感觉。\n保持自然呼吸，不触摸脉搏。'),
    'respiration_attention': ('呼吸注意', '关注自然呼吸带来的感觉。\n不用刻意加深、放慢或配合节律。'),
    'visual_rhythm': ('视觉节律', '关注中央圆点的变化。\n遇到更亮的圆点时按1，其他时候不按键。\n本段任务不使用2。'),
    'body_feedback_synchrony': ('身体与反馈', ''),
    'gradcpt_standard': ('目标检测', '城市图像出现时按1。\n山景图像出现时不按键，本段任务不使用2。'),
    'gradcpt_reversed': ('反转动作映射', '山景图像出现时按1。\n城市图像出现时不按键，本段任务不使用2。'),
}
DEFAULT_TIMINGS = dict(instruction_s=1.5, task_s=12., synchrony_s=4.,
                       confidence_s=2., fixation_s=3.)
BASE_SITE_FIELDS = (
    'task_platform_version', 'device_to_task_clock_mapping_id',
    'clock_residual_and_drift_report', 'mri_trigger_transport_and_semantics',
    'dummy_and_first_analysis_volume_rule', 'display_output_measurement_report',
    'response_device_and_mapping', 'approved_protocol_and_parameter_version',
)
RESPONSE_CONTRACT = 'two_button_binary_v1'
RATING_OPTIONS = {
    'synchrony': ('刚才，视觉反馈与自己的心跳同步吗？', ('不同步', '同步')),
    'confidence': ('你对刚才的判断有把握吗？', ('较没把握', '较有把握')),
}


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    value = float(value)
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')
    return value


class TaskPresentation:
    """One block with explicit instruction, trigger, task and optional ratings.

    ``instruction_s`` is a minimum duration, then button 1 or 2 enters trigger
    wait. Only the separate ``trigger`` action starts the block. Both response
    buttons may be operated by one hand; button 2 is unused in detection tasks.
    Binary ratings lock on their first 1/2 press without another confirmation
    and never shorten fixed pages. No response is missing, with no default.
    This endpoint replaces, and is not interchangeable with, the earlier
    0--100 synchrony slider or four-level confidence scale. It cannot identify
    an explicit "unable to judge" response; omission alone never establishes
    that reason. Escape is an operator action, not the patient's panic ball.

    Real feedback adapters are callables ``feedback_source(now_s) -> events``.
    Each event supplies cue_id, requested_onset_s, available_at_s, clock_id,
    is_synthetic=False, quality_ok=True. These are *software cue requests*,
    never assertions of a measured physical output or an ECG R wave. The
    adapter is responsible for the approved current/replay linkage and causal
    quality checks. No synthetic source is substituted when it is absent.
    """
    def __init__(self, condition_row, *, mode='demo', clock_id='synthetic_task_monotonic',
                 timings=None, site_profile=None, gradcpt_materials=None, seed=0,
                 feedback_source=None):
        if mode not in ('demo', 'real'):
            raise ValueError('mode must be demo or real')
        if not isinstance(condition_row, dict) or condition_row.get('family') not in FAMILIES:
            raise ValueError('Unknown condition family')
        if not isinstance(condition_row.get('condition_id'), str) or not condition_row['condition_id']:
            raise ValueError('condition_id is required')
        if not isinstance(clock_id, str) or not clock_id:
            raise ValueError('clock_id is required')
        params = condition_row.get('parameter_values')
        if params is not None and not isinstance(params, dict):
            raise ValueError('parameter_values must be a mapping')
        self.condition = deepcopy(condition_row)
        self.condition_id = condition_row['condition_id']
        self.family = condition_row['family']
        self.params = deepcopy(params or {})
        self.mode, self.clock_id = mode, clock_id
        self.is_synthetic = mode == 'demo'
        supplied = dict(timings or {})
        if set(supplied) - set(DEFAULT_TIMINGS):
            raise ValueError('Unknown timing field')
        self.timings = {k: _number(supplied.get(k, v), k, positive=True)
                        for k, v in DEFAULT_TIMINGS.items()}
        self.feedback_source = feedback_source
        self.materials = deepcopy(gradcpt_materials)
        if mode == 'real':
            self._validate_real(site_profile, supplied, params)
            if 'synthetic' in clock_id.lower():
                raise ValueError('Real mode requires an explicit calibrated task clock_id')
        self.attention = self.params.get('attention', 'heartbeat')
        self.linkage = self.params.get('linkage', 'current')
        if self.attention not in ('heartbeat', 'external') or self.linkage not in ('current', 'replay'):
            raise ValueError('Invalid attention or linkage')
        self.interval_s = self._parameter('interval_s', 1.) if self.family == 'visual_rhythm' else None
        self.pulse_width_s = self._parameter('pulse_width_s', .12) if self.family in (
            'visual_rhythm', 'body_feedback_synchrony') else None
        if self.interval_s and self.pulse_width_s >= self.interval_s:
            raise ValueError('pulse_width_s must be less than interval_s')
        self.period_s = self._parameter('period_s', .8) if self.family.startswith('gradcpt_') else None
        self.probability = self.params.get('mountain_probability', .1) if self.period_s else self.params.get('target_probability', .2)
        self.probability = _number(self.probability, 'trial probability')
        if not 0 < self.probability < 1:
            raise ValueError('trial probability must be between zero and one')
        rng = random.Random(seed)
        step = self.period_s or self.interval_s or 1.
        self._trials = [rng.random() < self.probability
                        for _ in range(math.ceil(self.timings['task_s'] / step) + 2)]
        self.phase = 'not_started'
        self._last_time = self._phase_start = self._task_start = None
        self._rating = None
        self._events = []
        self._responded = set()
        self._feedback_ids = set()
        self._last_feedback_onset = None
        self._synchrony_value = None

    def _parameter(self, name, demo_default):
        if self.mode == 'real' and name not in self.params:
            raise ValueError(f'Real mode requires calibrated parameter {name}')
        return _number(self.params.get(name, demo_default), name, positive=True)

    def _validate_real(self, profile, timings, params):
        profile = profile or {}
        if (profile.get('stage') not in ('site_calibrated', 'validated_pilot')
                or profile.get('human_acquisition_ready') is not True
                or profile.get('task_platform') != 'PsychoPy'):
            raise ValueError('Real mode requires a site-calibrated PsychoPy profile')
        missing = [key for key in BASE_SITE_FIELDS if not profile.get(key)]
        if missing:
            raise ValueError('Missing site calibration evidence: ' + ', '.join(missing))
        needed = {'instruction_s', 'task_s', 'fixation_s'}
        if self.family == 'body_feedback_synchrony':
            needed |= {'synchrony_s', 'confidence_s'}
        if not needed <= set(timings):
            raise ValueError('Real mode requires explicit calibrated phase timings')
        if not params or 'synthetic_preset' in params:
            raise ValueError('Real mode requires approved parameter_values')
        if self.family in ('heartbeat_attention', 'respiration_attention', 'body_feedback_synchrony'):
            if not profile.get('attention_manipulation_pilot_report'):
                raise ValueError('Missing attention manipulation pilot report')
        if self.family == 'visual_rhythm' and 'target_probability' not in params:
            raise ValueError('Missing calibrated target_probability')
        if self.family == 'body_feedback_synchrony':
            required = ('physiology_stream_format_and_transport', 'causal_detector_id_and_version',
                        'independent_reference_and_scope', 'maximum_timing_error_and_dropout_rules',
                        'replay_bank_and_matching_rules')
            if any(not profile.get(key) for key in required):
                raise ValueError('Missing physiological timing and replay calibration evidence')
            delay = _number(profile.get('calibrated_delay_seconds'), 'calibrated_delay_seconds')
            if delay < 0:
                raise ValueError('calibrated_delay_seconds must not be negative')
            if not {'attention', 'linkage'} <= set(params) or not callable(self.feedback_source):
                raise ValueError('Real body feedback requires attention/linkage and feedback_source adapter')
        if self.family.startswith('gradcpt_'):
            if not profile.get('gradcpt_timing_and_scoring_report'):
                raise ValueError('Missing GradCPT timing/scoring calibration report')
            if 'mountain_probability' not in params:
                raise ValueError('Missing calibrated mountain_probability')
            manifest = self.materials or {}
            if manifest.get('licensed_for_use') is not True or not manifest.get('license_reference'):
                raise ValueError('Real GradCPT requires licensed materials and license_reference')
            for category in ('city_images', 'mountain_images'):
                paths = manifest.get(category)
                if not isinstance(paths, list) or not paths or any(
                        not isinstance(p, str) or not Path(p).is_file() for p in paths):
                    raise ValueError(f'Missing local licensed GradCPT materials: {category}')

    def _time(self, now_s):
        now = _number(now_s, 'timestamp_s')
        if now < 0 or (self._last_time is not None and now < self._last_time):
            raise ValueError('Caller task clock moved backwards or is negative')
        return now

    def _emit(self, event, now, **fields):
        self._events.append(dict(event=event, timestamp_s=now, clock_id=self.clock_id,
            timestamp_basis='caller_task_clock', is_synthetic=self.is_synthetic,
            physical_trigger_time_s=None, measured_output_time_s=None,
            response_contract=RESPONSE_CONTRACT, **fields))

    def _enter(self, phase, now):
        self.phase, self._phase_start = phase, now
        self._rating = None
        if phase in ('synchrony', 'confidence'):
            question, labels = RATING_OPTIONS[phase]
            self._rating = dict(field=phase+'_binary', scale='binary_v1', question=question,
                value=None, confirmed=False, low=1, high=2, step=1, missing_reason=None,
                options=[dict(key=str(i), value=i, label=label) for i,label in enumerate(labels, 1)],
                response_key=None, response_time_s=None)
            if phase == 'confidence':
                self._rating['preceding_synchrony_response_available'] = self._synchrony_value is not None
        if phase == 'task':
            self._task_start = now
        self._emit('phase_changed', now, phase=phase)

    def start(self, now_s):
        if self.phase != 'not_started':
            raise ValueError('Presentation has already started')
        now = self._time(now_s)
        self._last_time = now
        self._enter('instruction', now)
        return self.view(now)

    def advance(self, now_s, action=None):
        if self.phase == 'not_started':
            raise ValueError('Call start before advance')
        now = self._time(now_s)
        aliases = {'esc': 'escape', '5': 'trigger', '1': 'button_1', '2': 'button_2'}
        action = aliases.get(action, action)
        if action not in (None, 'button_1', 'button_2', 'trigger', 'escape'):
            raise ValueError('Unknown action')
        self._last_time = now
        if self.phase in ('complete', 'aborted'):
            return self.view(now)
        if action == 'escape':
            self._emit('aborted', now, previous_phase=self.phase)
            self._enter('aborted', now)
            return self.view(now)
        elapsed = now - self._phase_start
        if self.phase == 'instruction':
            if action in ('button_1', 'button_2') and elapsed >= self.timings['instruction_s']:
                self._enter('trigger_wait', now)
        elif self.phase == 'trigger_wait':
            if action == 'trigger':
                self._emit('trigger_input_observed', now, trigger_basis='software_input')
                self._enter('task', now)
        elif self.phase == 'task':
            if elapsed >= self.timings['task_s']:
                self._emit('task_completed', now, planned_duration_s=self.timings['task_s'])
                self._enter('synchrony' if self.family == 'body_feedback_synchrony' else 'fixation', now)
            else:
                if self.family == 'body_feedback_synchrony' and self.mode == 'real':
                    self._poll_feedback(now)
                if action == 'button_1' and (self.period_s or self.interval_s):
                    self._record_response(now)
        elif self.phase in ('synchrony', 'confidence'):
            if elapsed >= self.timings[self.phase + '_s']:
                r = self._rating
                details = dict(field=r['field'], scale=r['scale'], value=r['value'],
                    confirmed=r['confirmed'], response_key=r['response_key'],
                    response_time_s=r['response_time_s'],
                    missing_reason=None if r['confirmed'] else 'no_response')
                if self.phase == 'synchrony':
                    self._synchrony_value = r['value']
                else:
                    details['preceding_synchrony_response_available'] = self._synchrony_value is not None
                self._emit('rating_recorded', now, **details)
                self._enter('confidence' if self.phase == 'synchrony' else 'fixation', now)
            elif not self._rating['confirmed']:
                if action in ('button_1', 'button_2'):
                    r = self._rating
                    value = 1 if action == 'button_1' else 2
                    r.update(value=value, confirmed=True, response_key=str(value), response_time_s=elapsed)
                    self._emit('rating_response', now, field=r['field'], scale=r['scale'],
                        value=value, response_key=str(value), response_time_s=elapsed)
        elif self.phase == 'fixation' and elapsed >= self.timings['fixation_s']:
            self._enter('complete', now)
        return self.view(now)

    def _record_response(self, now):
        elapsed = now - self._task_start
        if self.period_s or self.interval_s:
            period = self.period_s or self.interval_s
            trial = min(int(elapsed / period), len(self._trials) - 2)
            category = 'mountain' if self._trials[trial] else 'city'
            expected = (category == 'city' if self.family == 'gradcpt_standard' else category == 'mountain') if self.period_s else self._trials[trial]
            self._emit('task_response', now, trial_index=trial, response_time_s=elapsed-trial*period,
                       repeated=trial in self._responded, expected_response=expected, response_key='1')
            self._responded.add(trial)
        else:
            self._emit('task_response', now, trial_index=None, response_time_s=None,
                       repeated=False, expected_response=None)

    def _poll_feedback(self, now):
        events = self.feedback_source(now)
        if not isinstance(events, (list, tuple)):
            raise ValueError('feedback_source must return a list of software cue requests')
        checked = []
        ids = set(self._feedback_ids)
        for event in events:
            if not isinstance(event, dict):
                raise ValueError('Invalid feedback request')
            onset = _number(event.get('requested_onset_s'), 'requested_onset_s')
            available = _number(event.get('available_at_s'), 'available_at_s')
            cue_id = event.get('cue_id')
            if (not isinstance(cue_id, str) or not cue_id or cue_id in ids
                    or event.get('clock_id') != self.clock_id or event.get('is_synthetic') is not False
                    or event.get('quality_ok') is not True or not self._task_start <= onset <= now
                    or not self._task_start <= available <= onset):
                raise ValueError('Invalid, duplicate, future or synthetic real-feedback request')
            ids.add(cue_id)
            checked.append((cue_id, onset, available))
        for cue_id, onset, available in checked:
            self._feedback_ids.add(cue_id)
            self._last_feedback_onset = max(onset, self._last_feedback_onset or onset)
            self._emit('feedback_request_received', now, cue_id=cue_id,
                       requested_onset_s=onset, available_at_s=available,
                       cue_timing_basis='adapter_software_request')

    def _stimulus(self, task_elapsed):
        result = dict(kind='fixation', active=False)
        if self.phase != 'task':
            return result
        if self.family == 'visual_rhythm':
            trial = min(int(task_elapsed / self.interval_s), len(self._trials) - 2)
            active = task_elapsed - trial*self.interval_s < self.pulse_width_s
            return dict(kind='visual_rhythm', active=active, intensity=1. if self._trials[trial] else .65,
                        trial_index=trial, target=self._trials[trial])
        if self.family == 'body_feedback_synchrony':
            if self.mode == 'demo':
                period, offset = (.83, .17) if self.linkage == 'current' else (.91, .43)
                active = task_elapsed >= offset and (task_elapsed-offset) % period < self.pulse_width_s
            else:
                now = self._task_start + task_elapsed
                active = self._last_feedback_onset is not None and 0 <= now-self._last_feedback_onset < self.pulse_width_s
            return dict(kind='feedback_ring', active=active, intensity=1.)
        if self.period_s:
            trial = min(int(task_elapsed / self.period_s), len(self._trials) - 2)
            category = 'mountain' if self._trials[trial] else 'city'
            next_category = 'mountain' if self._trials[trial+1] else 'city'
            def image_token(cat, index):
                if self.is_synthetic:
                    return f'demo_{cat}_{index % 3}'
                paths = self.materials[cat+'_images']
                return paths[index % len(paths)]
            expected = category == ('city' if self.family == 'gradcpt_standard' else 'mountain')
            return dict(kind='gradcpt', active=True, trial_index=trial, category=category,
                        expected_response=expected, from_image=image_token(category, trial),
                        to_image=image_token(next_category, trial+1), mix=(task_elapsed%self.period_s)/self.period_s,
                        placeholder=self.is_synthetic)
        return result

    def view(self, now_s):
        now = self._time(now_s)
        elapsed = 0. if self._phase_start is None else now-self._phase_start
        task_elapsed = 0. if self._task_start is None else min(self.timings['task_s'], now-self._task_start)
        title, instruction = FAMILIES[self.family]
        if self.family == 'body_feedback_synchrony':
            instruction = ('关注自己的心跳感觉。' if self.attention == 'heartbeat' else '关注中央圆点的明暗变化。') + '\n本段先不用按键。\n稍后用1或2判断视觉反馈是否与心跳同步。'
        phase_duration = self.timings.get(self.phase+'_s')
        status = {'complete': '本段已完成', 'aborted': '本段已停止', 'trigger_wait': '等待任务开始'}.get(self.phase, '请按照指令完成本段任务')
        return dict(phase=self.phase, family=self.family, condition_id=self.condition['condition_id'],
            title=title, instruction=instruction, is_synthetic=self.is_synthetic, clock_id=self.clock_id,
            task_elapsed_s=task_elapsed, duration_s=self.timings['task_s'], phase_elapsed_s=elapsed,
            phase_duration_s=phase_duration, stimulus=self._stimulus(task_elapsed),
            rating=deepcopy(self._rating), task_status=status, response_contract=RESPONSE_CONTRACT)

    def drain_events(self):
        events, self._events = self._events, []
        return events
