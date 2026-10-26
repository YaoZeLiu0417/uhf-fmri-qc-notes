from pathlib import Path
import pytest
from experiments.interoception.psychopy_bridge import NamedTaskClock, PsychoPyBlockBridge


SPACE = dict(clock_id='synthetic_task_clock', definition_sha256='registry_hash',
             is_synthetic=True, conditions=[{'condition_id':'a'}, {'condition_id':'b'}])


class FakeClock:
    def __init__(self, now=1.):self.now=now
    def getTime(self):return self.now


class FakeWindow:
    def __init__(self):self.callbacks=[]
    def callOnFlip(self, callback):self.callbacks.append(callback)
    def flip(self):
        callbacks,self.callbacks=self.callbacks,[]
        for callback in callbacks:callback()


def setup():
    native=FakeClock();clock=NamedTaskClock('synthetic_task_clock',native)
    return PsychoPyBlockBridge(SPACE,'run1','session_hash'),FakeWindow(),native,clock,[]


def command(**updates):
    return dict(dict(kind='next_block_recommendation',run_id='run1',block_id='block1',
        condition_id='a',role='development',decision_time_s=.5,
        definition_hash='session_hash',is_synthetic=True),**updates)


def receipt(**updates):
    snapshot=dict(definition_hash='session_hash',freeze_time_s=5.,
                  optimizer=dict(run_id='run1',frozen=True))
    snapshot.update(updates)
    return dict(status='frozen',snapshot=snapshot)


def test_onset_comes_from_executed_flip_callback_not_queue_or_predicted_time():
    bridge,window,native,clock,events=setup();cmd=command()
    result=bridge.queue_start_on_flip(window,cmd,clock,2.,events.append)
    assert result['status']=='queued_for_flip' and events==[]
    cmd['condition_id']='b'  # cannot mutate the queued command snapshot
    native.now=1.234;window.flip()
    assert len(events)==1 and events[0]['onset_s']==1.234
    assert events[0]['command']['condition_id']=='a'
    assert events[0]['actual_flip_callback_time_s']==1.234
    assert events[0]['onset_basis']=='software_flip_callback'
    assert events[0]['physical_trigger_time_s'] is None
    assert events[0]['measured_output_time_s'] is None
    assert events[0]['planned_duration_s']==2.
    assert events[0]['duration_basis']=='planned_until_block_ended'


@pytest.mark.parametrize('bad',[{'definition_hash':'other'}, {'condition_id':'unknown'},
    {'run_id':'run2'}, {'role':'test'}, {'kind':'other'}, {'is_synthetic':False},
    {'decision_time_s':2.}, {'clock_id':'wrong'}])
def test_wrong_definition_condition_run_phase_or_time_never_registers_callback(bad):
    bridge,window,native,clock,events=setup()
    with pytest.raises(ValueError):bridge.queue_start_on_flip(window,command(**bad),clock,2.,events.append)
    assert window.callbacks==[] and events==[]


def test_duplicate_and_concurrent_commands_cannot_be_queued_or_replayed():
    bridge,window,native,clock,events=setup()
    bridge.queue_start_on_flip(window,command(),clock,1.,events.append)
    with pytest.raises(ValueError,match='pending'):bridge.queue_start_on_flip(window,command(),clock,1.,events.append)
    window.flip();native.now=2.
    bridge.queue_end_on_flip(window,'block1',clock,events.append);window.flip();native.now=3.
    with pytest.raises(ValueError,match='Duplicate'):bridge.queue_start_on_flip(window,command(),clock,1.,events.append)
    with pytest.raises(ValueError,match='stale'):bridge.queue_start_on_flip(window,command(block_id='new'),clock,1.,events.append)


def test_clock_backwards_at_flip_does_not_emit_a_false_onset_and_is_not_replayed():
    bridge,window,native,clock,events=setup()
    bridge.queue_start_on_flip(window,command(),clock,1.,events.append)
    native.now=.9
    with pytest.raises(ValueError,match='backwards'):window.flip()
    assert events==[]
    native.now=3.
    with pytest.raises(ValueError,match='Duplicate'):bridge.queue_start_on_flip(window,command(),clock,1.,events.append)


def test_clock_identity_and_object_cannot_be_silently_replaced():
    bridge,window,native,clock,events=setup()
    wrong=NamedTaskClock('wrong_clock',native)
    with pytest.raises(ValueError,match='identity'):bridge.queue_start_on_flip(window,command(),wrong,1.,events.append)
    bridge.queue_start_on_flip(window,command(),clock,1.,events.append);window.flip();native.now=2.
    bridge.queue_end_on_flip(window,'block1',clock,events.append);window.flip();native.now=3.
    replacement=NamedTaskClock('synthetic_task_clock',native)
    with pytest.raises(ValueError,match='object'):bridge.queue_start_on_flip(window,command(block_id='b2',decision_time_s=2.5),replacement,1.,events.append)


def test_test_phase_requires_matching_freeze_receipt_and_new_time_boundary():
    bridge,window,native,clock,events=setup()
    with pytest.raises(ValueError):bridge.set_phase('test',not_before_s=5.,freeze_receipt={'status':'not_frozen'})
    with pytest.raises(ValueError):bridge.set_phase('test',not_before_s=5.,freeze_receipt=receipt(definition_hash='different'))
    with pytest.raises(ValueError):bridge.set_phase('test',not_before_s=4.,freeze_receipt=receipt())
    bridge.set_phase('test',not_before_s=5.,freeze_receipt=receipt())
    native.now=6.
    with pytest.raises(ValueError):bridge.queue_start_on_flip(window,command(),clock,1.,events.append)
    with pytest.raises(ValueError):bridge.queue_start_on_flip(window,command(role='test',decision_time_s=4.5),clock,1.,events.append)
    bridge.queue_start_on_flip(window,command(role='test',decision_time_s=5.5),clock,1.,events.append)
    native.now=6.2;window.flip()
    assert events[0]['role']=='test' and events[0]['onset_s']==6.2


def test_no_phase_switch_with_pending_callback_or_without_actual_block_end():
    bridge,window,native,clock,events=setup()
    bridge.queue_start_on_flip(window,command(),clock,5.,events.append)
    with pytest.raises(ValueError,match='idle'):bridge.set_phase('test',not_before_s=5.,freeze_receipt=receipt())
    window.flip();native.now=3.
    with pytest.raises(ValueError,match='actual end'):bridge.queue_start_on_flip(window,command(block_id='block2',decision_time_s=2.5),clock,1.,events.append)
    with pytest.raises(ValueError,match='idle'):bridge.set_phase('test',not_before_s=5.,freeze_receipt=receipt())
    assert len(events)==1


def test_actual_end_comes_from_its_flip_and_may_differ_from_the_planned_duration():
    bridge,window,native,clock,events=setup()
    bridge.queue_start_on_flip(window,command(),clock,5.,events.append);window.flip()
    native.now=7.
    bridge.queue_end_on_flip(window,'block1',clock,events.append)
    assert len(events)==1
    native.now=7.4;window.flip()
    ended=events[1]
    assert ended['kind']=='block_ended' and ended['offset_s']==7.4
    assert ended['planned_duration_s']==5. and ended['software_duration_s']==pytest.approx(6.4)
    assert ended['actual_flip_callback_time_s']==7.4
    assert ended['measured_output_time_s'] is None and ended['physical_trigger_time_s'] is None
    native.now=8.
    bridge.queue_start_on_flip(window,command(block_id='block2',decision_time_s=7.5),clock,1.,events.append)
    window.flip();assert events[-1]['kind']=='block_started'


def test_unknown_duplicate_and_end_before_start_are_rejected():
    bridge,window,native,clock,events=setup()
    with pytest.raises(ValueError,match='unstarted'):bridge.queue_end_on_flip(window,'block1',clock,events.append)
    bridge.queue_start_on_flip(window,command(),clock,1.,events.append);window.flip()
    with pytest.raises(ValueError,match='unknown'):bridge.queue_end_on_flip(window,'other',clock,events.append)
    bridge.queue_end_on_flip(window,'block1',clock,events.append)
    with pytest.raises(ValueError,match='does not follow'):window.flip()
    assert len(events)==1
    native.now=2.
    with pytest.raises(ValueError,match='Duplicate'):bridge.queue_end_on_flip(window,'block1',clock,events.append)


def test_end_callback_is_not_replayed_and_completed_end_cannot_be_queued_again():
    bridge,window,native,clock,events=setup()
    bridge.queue_start_on_flip(window,command(),clock,1.,events.append);window.flip()
    native.now=2.;bridge.queue_end_on_flip(window,'block1',clock,events.append)
    callback=window.callbacks[0];window.flip()
    with pytest.raises(ValueError,match='twice'):callback()
    with pytest.raises(ValueError,match='Duplicate'):bridge.queue_end_on_flip(window,'block1',clock,events.append)
    assert len(events)==2


def test_start_and_end_events_dispatch_to_the_actual_session_controller():
    from experiments.interoception.session import NeuroadaptiveSession
    from experiments.interoception.taskspace import load_taskspace
    cfg=Path(__file__).resolve().parents[1]/'experiments/interoception/taskspace.synthetic.json'
    space=load_taskspace(cfg)
    session=NeuroadaptiveSession(space,'bridge_integration')
    recommendation=session.propose(0.)['command']
    bridge=PsychoPyBlockBridge(space,session.run_id,session.definition_hash)
    native=FakeClock(1.);clock=NamedTaskClock(space['clock_id'],native)
    window,events=FakeWindow(),[]
    bridge.queue_start_on_flip(window,recommendation,clock,7.,events.append)
    window.flip();session.dispatch(events.pop(0))
    assert session.blocks[-1]['planned_duration_s']==7. and not session.blocks[-1]['ended']
    native.now=10.;bridge.queue_end_on_flip(window,recommendation['block_id'],clock,events.append)
    window.flip();session.dispatch(events.pop(0))
    assert session.blocks[-1]['ended'] and session.blocks[-1]['actual_offset_s']==10.
    assert session.blocks[-1]['duration_s']==9.
