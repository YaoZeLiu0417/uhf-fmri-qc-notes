import copy
import json
import math
import pytest
from experiments.interoception.presentation import (
    BASE_SITE_FIELDS, FAMILIES, TaskPresentation,
)


TIMINGS = dict(instruction_s=1., task_s=4., synchrony_s=2., confidence_s=2., fixation_s=1.)


def condition(family='body_feedback_synchrony', **params):
    return dict(condition_id='candidate_1', family=family, parameter_values=params)


def flow(family='body_feedback_synchrony', **kwargs):
    return TaskPresentation(condition(family), timings=TIMINGS, **kwargs)


def begin(p):
    assert p.start(0)['phase'] == 'instruction'
    assert p.advance(1, '1')['phase'] == 'trigger_wait'
    assert p.advance(2, 'trigger')['phase'] == 'task'
    return p


def calibrated_profile():
    return dict({key: 'independent_site_report_v1' for key in BASE_SITE_FIELDS},
        stage='site_calibrated', human_acquisition_ready=True, task_platform='PsychoPy',
        attention_manipulation_pilot_report='attention_pilot_v1',
        physiology_stream_format_and_transport='physio_stream_v1',
        causal_detector_id_and_version='causal_detector_v1',
        independent_reference_and_scope='peripheral_pulse_not_ecg_rwave',
        maximum_timing_error_and_dropout_rules='bounded_causal_drop_v1',
        replay_bank_and_matching_rules='private_replay_v1', calibrated_delay_seconds=.1,
        gradcpt_timing_and_scoring_report='approved_gradcpt_pilot_v1')


@pytest.mark.parametrize('family', tuple(FAMILIES))
def test_all_families_have_complete_explicit_flow_with_ratings_only_for_probe(family):
    p = begin(flow(family))
    next_phase = p.advance(6)['phase']
    if family == 'body_feedback_synchrony':
        assert next_phase == 'synchrony'
        assert p.advance(8)['phase'] == 'confidence'
        assert p.advance(10)['phase'] == 'fixation'
        assert p.advance(11)['phase'] == 'complete'
    else:
        assert next_phase == 'fixation'
        assert p.advance(7)['phase'] == 'complete'
    events = p.drain_events()
    assert [r['timestamp_s'] for r in events] == sorted(r['timestamp_s'] for r in events)
    assert all(r['physical_trigger_time_s'] is None and r['measured_output_time_s'] is None for r in events)
    assert all(r['timestamp_basis'] == 'caller_task_clock' and r['is_synthetic'] for r in events)
    ratings = [r for r in events if r['event'] == 'rating_recorded']
    assert len(ratings) == (2 if family == 'body_feedback_synchrony' else 0)
    assert p.drain_events() == []


def test_either_instruction_button_and_separate_scanner_trigger_are_required():
    p = flow(); p.start(0)
    assert p.advance(.5, '1')['phase'] == 'instruction'
    assert p.advance(5)['phase'] == 'instruction'
    assert p.advance(5, '2')['phase'] == 'trigger_wait'
    assert p.advance(5.1, '1')['phase'] == 'trigger_wait'
    assert p.advance(5.2, '2')['phase'] == 'trigger_wait'
    assert p.advance(100)['phase'] == 'trigger_wait'
    assert p.advance(101, 'trigger')['phase'] == 'task'
    trigger = [r for r in p.drain_events() if r['event'] == 'trigger_input_observed']
    assert trigger[0]['timestamp_s'] == 101
    assert trigger[0]['trigger_basis'] == 'software_input'
    assert trigger[0]['physical_trigger_time_s'] is None


def test_first_binary_press_locks_rating_without_confirmation_and_keeps_fixed_pages():
    p = begin(flow()); p.advance(6)
    view = p.advance(6.1, '2')
    assert view['phase'] == 'synchrony' and view['rating']['value'] == 2
    assert view['rating']['confirmed'] is True
    assert p.advance(7, '1')['rating']['value'] == 2
    assert p.advance(7.99)['phase'] == 'synchrony'
    assert p.advance(8)['phase'] == 'confidence'
    assert p.advance(8.1, '1')['phase'] == 'confidence'
    assert p.advance(8.2, '2')['rating']['value'] == 1
    assert p.advance(9.99)['phase'] == 'confidence'
    assert p.advance(10)['phase'] == 'fixation'
    ratings = [r for r in p.drain_events() if r['event'] == 'rating_recorded']
    assert [(r['field'], r['value'], r['confirmed']) for r in ratings] == [('synchrony_binary',2,True), ('confidence_binary',1,True)]
    assert [r['response_key'] for r in ratings] == ['2', '1']
    assert all(r['scale'] == 'binary_v1' and r['response_time_s'] == pytest.approx(.1) for r in ratings)
    assert ratings[1]['preceding_synchrony_response_available'] is True


def test_no_binary_response_is_missing_with_no_default_or_inferred_inability():
    p = begin(flow()); p.advance(6)
    assert p.view(6)['rating']['value'] is None
    p.advance(8); p.advance(10)
    ratings = [r for r in p.drain_events() if r['event'] == 'rating_recorded']
    assert [r['value'] for r in ratings] == [None, None]
    assert [r['missing_reason'] for r in ratings] == ['no_response', 'no_response']
    assert all(r['confirmed'] is False for r in ratings)
    assert all(r['response_key'] is None and r['response_time_s'] is None for r in ratings)
    assert ratings[1]['preceding_synchrony_response_available'] is False


def test_binary_questions_are_explicit_new_endpoints_and_old_slider_actions_are_rejected():
    p = begin(flow()); p.advance(6)
    rating = p.view(6)['rating']
    assert rating['field'] == 'synchrony_binary' and rating['scale'] == 'binary_v1'
    assert rating['low'] == 1 and rating['high'] == 2
    assert [r['label'] for r in rating['options']] == ['不同步', '同步']
    assert '同步吗' in rating['question']
    for action in ('left', 'right', 'confirm', 'space', 'unable', 'u', 'respond'):
        with pytest.raises(ValueError, match='Unknown action'):p.advance(6.1, action)
    assert p.advance(8)['rating']['field'] == 'confidence_binary'
    assert [r['label'] for r in p.view(8)['rating']['options']] == ['较没把握', '较有把握']


@pytest.mark.parametrize('attention', ['heartbeat', 'external'])
def test_probe_instructions_blind_to_current_replay_source(attention):
    rows = [condition(attention=attention, linkage=source) for source in ('current','replay')]
    presentations = [TaskPresentation(row, timings=TIMINGS) for row in rows]
    instructions = [p.start(0)['instruction'] for p in presentations]
    assert instructions[0] == instructions[1]
    for word in ('current','replay','合成','模拟','同步反馈','异步反馈'):
        assert word not in instructions[0]
    public_view = presentations[0].view(0)
    assert 'linkage' not in public_view and 'parameter_values' not in public_view


@pytest.mark.parametrize('family', ['heartbeat_attention', 'respiration_attention'])
def test_body_attention_has_no_external_pacing_stimulus(family):
    p = begin(flow(family))
    for t in (2., 2.1, 2.83, 3.1, 4.7, 5.9):
        assert p.advance(t)['stimulus'] == dict(kind='fixation', active=False)


def test_gradcpt_demo_is_deterministic_placeholder_and_reversal_changes_response_mapping():
    standard = begin(flow('gradcpt_standard', seed=9))
    reversed_ = begin(flow('gradcpt_reversed', seed=9))
    for t in (2., 2.2, 2.8, 3.7, 5.9):
        first = standard.advance(t)['stimulus']; second = reversed_.advance(t)['stimulus']
        assert first['kind'] == 'gradcpt' and first['placeholder'] is True
        assert first['from_image'].startswith('demo_') and 0 <= first['mix'] < 1
        assert first['category'] == second['category']
        assert first['expected_response'] is not second['expected_response']
    standard.advance(5.94, '2')  # unused task button does not become a go response
    standard.advance(5.95, '1'); standard.advance(5.96, '1')
    responses = [r for r in standard.drain_events() if r['event'] == 'task_response']
    assert [r['repeated'] for r in responses] == [False, True]
    assert all(r['response_key'] == '1' for r in responses)
    assert responses[0]['response_time_s'] >= 0


def test_visual_target_schedule_has_seeded_brightness_and_finite_pulses():
    p = begin(flow('visual_rhythm', seed=2))
    active = p.advance(2)['stimulus']; inactive = p.advance(2.2)['stimulus']
    assert active['kind'] == 'visual_rhythm' and active['active'] is True
    assert active['intensity'] in (.65, 1.) and inactive['active'] is False


def test_view_is_detached_json_safe_and_never_emits_or_advances():
    p = begin(flow()); p.advance(6); p.drain_events()
    first = p.view(6.1); first['rating']['value'] = 0
    assert p.view(6.1)['rating']['value'] is None
    assert p.view(20)['phase'] == 'synchrony'
    assert p.drain_events() == []
    assert json.loads(json.dumps(p.view(6.2), allow_nan=False))['condition_id'] == p.condition_id


@pytest.mark.parametrize('now', [-1, math.nan, math.inf, True])
def test_invalid_clock_never_enters_presentation(now):
    p = flow()
    with pytest.raises(ValueError):p.start(now)
    assert p.phase == 'not_started' and p.drain_events() == []


def test_clock_backwards_and_unknown_actions_are_rejected_without_event():
    p = begin(flow()); p.drain_events()
    with pytest.raises(ValueError, match='backwards'):p.advance(1.99)
    with pytest.raises(ValueError, match='Unknown action'):p.advance(2.1, 'nonsense')
    assert p.drain_events() == []
    assert p.advance(2.1, 'escape')['phase'] == 'aborted'
    assert p.advance(100)['phase'] == 'aborted'
    with pytest.raises(ValueError):p.start(101)


@pytest.mark.parametrize('site', [{}, {'human_acquisition_ready':True},
    dict(calibrated_profile(), display_output_measurement_report=None)])
def test_real_mode_cannot_be_enabled_by_one_readiness_boolean(site):
    with pytest.raises(ValueError):
        TaskPresentation(condition('heartbeat_attention', attention='heartbeat'), mode='real',
                         site_profile=site, timings=TIMINGS)


def test_real_mode_requires_explicit_timings_and_approved_parameters():
    with pytest.raises(ValueError, match='explicit calibrated'):
        TaskPresentation(condition('heartbeat_attention', attention='heartbeat'), mode='real', site_profile=calibrated_profile())
    with pytest.raises(ValueError, match='approved parameter_values'):
        TaskPresentation(condition('heartbeat_attention', synthetic_preset=1), mode='real',
                         site_profile=calibrated_profile(), timings=TIMINGS)


def real_probe(source=None):
    return TaskPresentation(condition(attention='heartbeat', linkage='current', pulse_width_s=.12),
        mode='real', clock_id='calibrated_task_clock', timings=TIMINGS,
        site_profile=calibrated_profile(), feedback_source=source)


def test_real_body_feedback_requires_adapter_and_never_invents_a_live_pulse():
    with pytest.raises(ValueError, match='feedback_source'):real_probe()
    p = begin(real_probe(lambda now: []))
    assert p.advance(2.17)['stimulus']['active'] is False  # demo would flash here
    assert not p.is_synthetic and not any(r['is_synthetic'] for r in p.drain_events())


def test_real_adapter_requests_can_drive_software_cue_without_physical_timing_claims():
    requests = [dict(cue_id='c1', requested_onset_s=2.2, available_at_s=2.19,
                     clock_id='calibrated_task_clock', is_synthetic=False, quality_ok=True)]
    p = begin(real_probe(lambda now: requests if now == 2.2 else []))
    assert p.advance(2.2)['stimulus']['active'] is True
    assert p.advance(2.4)['stimulus']['active'] is False
    event = [r for r in p.drain_events() if r['event'] == 'feedback_request_received'][0]
    assert event['requested_onset_s'] == 2.2 and event['physical_trigger_time_s'] is None
    assert event['cue_timing_basis'] == 'adapter_software_request'


@pytest.mark.parametrize('change', [dict(is_synthetic=True), dict(quality_ok=False),
    dict(clock_id='wrong'), dict(requested_onset_s=2.3), dict(available_at_s=2.3),
    dict(available_at_s=2.21)])
def test_real_adapter_rejects_synthetic_future_wrong_clock_or_bad_quality(change):
    row = dict(cue_id='c1',requested_onset_s=2.2,available_at_s=2.19,
               clock_id='calibrated_task_clock',is_synthetic=False,quality_ok=True)
    row.update(change)
    p = begin(real_probe(lambda now: [row]))
    with pytest.raises(ValueError, match='real-feedback'):p.advance(2.2)
    assert not any(r['event'] == 'feedback_request_received' for r in p.drain_events())


def test_real_adapter_duplicate_cue_is_rejected():
    row = dict(cue_id='c1',requested_onset_s=2.2,available_at_s=2.19,
               clock_id='calibrated_task_clock',is_synthetic=False,quality_ok=True)
    p = begin(real_probe(lambda now: [row]));p.advance(2.2)
    with pytest.raises(ValueError, match='duplicate'):p.advance(2.3)


def test_real_gradcpt_requires_licensed_local_materials_and_never_returns_demo_tokens(tmp_path):
    kwargs = dict(mode='real',clock_id='calibrated_task_clock',timings=TIMINGS,site_profile=calibrated_profile())
    row = condition('gradcpt_standard', period_s=.8, mountain_probability=.1)
    with pytest.raises(ValueError, match='licensed'):TaskPresentation(row, **kwargs)
    city, mountain = tmp_path/'city.png', tmp_path/'mountain.png'
    city.write_bytes(b'manifest test only');mountain.write_bytes(b'manifest test only')
    manifest = dict(licensed_for_use=True,license_reference='institutional_license_v1',
                    city_images=[str(city)],mountain_images=[str(mountain)])
    p = begin(TaskPresentation(row,gradcpt_materials=manifest,**kwargs))
    stimulus = p.advance(2.1)['stimulus']
    assert stimulus['placeholder'] is False
    assert stimulus['from_image'] in (str(city),str(mountain))
    bad = copy.deepcopy(manifest);bad['mountain_images'] = [str(tmp_path/'absent.png')]
    with pytest.raises(ValueError, match='local licensed'):TaskPresentation(row,gradcpt_materials=bad,**kwargs)


def test_real_mode_rejects_synthetic_default_clock_even_with_site_evidence():
    with pytest.raises(ValueError, match='calibrated task clock_id'):
        TaskPresentation(condition('heartbeat_attention', attention='heartbeat'),
            mode='real', timings=TIMINGS, site_profile=calibrated_profile())


@pytest.mark.parametrize('kwargs', [dict(mode='other'),dict(timings={'task_s':0}),
    dict(timings={'task_s':math.inf}),dict(timings={'typo':1}),dict(clock_id='')])
def test_configuration_errors_are_rejected_before_start(kwargs):
    with pytest.raises(ValueError):TaskPresentation(condition(),**kwargs)
