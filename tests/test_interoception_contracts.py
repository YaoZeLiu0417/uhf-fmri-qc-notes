from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.interoception.contracts import (CueScheduler, build_selection_request, choose_delay,
    freeze_schedule, packet, private_output, simulation_config)
from experiments.interoception.simulate import run
from experiments.interoception.psychopy_task import toy_schedule
from experiments.interoception.psychopy_task import run as presentation

CONFIG=Path(__file__).resolve().parents[1]/'experiments/interoception/simulation_config.json'


def event(**updates):
    return dict(dict(event_id='synthetic_event',event_time_s=1.,available_time_s=1.04,
                     clock_id='clock',mapping_id='map',quality='good',is_synthetic=True),**updates)


def observations():
    return [dict(t,value=10+i,readout_id='rating_v0',available_time_s=20.,valid=True,is_synthetic=True)
            for i,t in enumerate(packet('synthetic_packet','d0',7))]


def request(rows):
    return build_selection_request(rows,['d0','d1'],'rating_v0','effect_precision',30.)


def test_current_event_deadlines_quality_and_duplicate_detection():
    s=CueScheduler('clock','map',.02)
    assert s.plan_current(event(),.3,1.04)['due_time_s']==pytest.approx(1.3)
    with pytest.raises(ValueError,match='duplicate'):s.plan_current(event(),.3,1.04)
    assert CueScheduler('clock','map',.02).plan_current(event(),.05,1.04)['reason']=='missed_deadline'
    assert CueScheduler('clock','map',.02).plan_current(event(quality='ambiguous'),.3,1.04)['reason']=='bad_quality'


@pytest.mark.parametrize('change',[{'clock_id':'other'},{'mapping_id':'other'},
    {'available_time_s':2.},{'event_time_s':2.},{'event_time_s':float('nan')}])
def test_unavailable_or_unmapped_pulses_cannot_schedule(change):
    with pytest.raises(ValueError):CueScheduler('clock','map',.02).plan_current(event(**change),.3,1.04)


@pytest.mark.parametrize('bad',['partial','duplicate','test','future','invalid','readout','nan','mixed_provenance'])
def test_selector_rejects_leakage_incomplete_contrasts_and_invalid_readouts(bad):
    rows=observations()
    if bad=='partial':rows.pop()
    elif bad=='duplicate':rows[1]['trial_id']=rows[0]['trial_id']
    elif bad=='test':rows[0]['role']='test'
    elif bad=='future':rows[0]['available_time_s']=31.
    elif bad=='invalid':rows[0]['valid']=False
    elif bad=='readout':rows[0]['readout_id']='different_model'
    elif bad=='nan':rows[0]['value']=float('nan')
    elif bad=='mixed_provenance':rows[0]['is_synthetic']=False
    with pytest.raises(ValueError):request(rows)


def test_full_packet_contrasts_fallback_and_external_boundary():
    rows=observations()
    for r in rows:r['value']={('heartbeat','current'):30,('heartbeat','replay'):10,('external','current'):15,('external','replay'):5}[r['attention'],r['linkage']]
    q=request(rows);assert q['estimates'][0]['contingency_effect']==15
    assert q['estimates'][0]['attention_dependence']==10
    assert choose_delay(q)=={'delay_id':'d1','policy':'balanced_fallback_only'}
    assert choose_delay(q,'d0')['policy']=='external_proposal_unvalidated'
    with pytest.raises(ValueError):choose_delay(q,'unknown')


def test_freeze_is_immutable_hash_bound_and_independent_of_new_outcomes():
    frozen=freeze_schedule(['d0','d1'],'rating_v0','objective_v0')
    assert frozen==freeze_schedule(['d0','d1'],'rating_v0','objective_v0')
    assert frozen.sha256!=freeze_schedule(['d1','d0'],'rating_v0','objective_v0').sha256
    with pytest.raises(FrozenInstanceError):frozen.readout_id='new_model'


def test_simulation_is_explicit_and_outputs_stay_private(tmp_path):
    cfg=json.loads(CONFIG.read_text());cfg['mode']='human'
    p=tmp_path/'bad.json';p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='synthetic'):simulation_config(p)
    with pytest.raises(ValueError,match='public repository'):private_output(CONFIG.parent/'session')


def test_end_to_end_mock_does_not_update_after_freeze_or_invent_mri(tmp_path):
    summary=run(CONFIG,tmp_path/'mock')
    lines=[json.loads(s) for s in (tmp_path/'mock/events.synthetic.jsonl').read_text().splitlines()]
    assert summary['trial_count']==24 and summary['test_trials']==12 and summary['participants']==0
    freeze=next(i for i,r in enumerate(lines) if r['kind']=='freeze')
    assert not any(r['kind']=='selector_request' for r in lines[freeze+1:])
    assert all(r['is_synthetic'] for r in lines)
    assert all(r['value'] is None for r in lines if r['kind']=='mri_readout_unavailable')
    assert all(r['measured_output_time_s'] is None for r in lines if r['kind']=='cue_receipt')


def test_late_current_pulse_plans_remain_skipped_without_fabricated_receipts(tmp_path):
    cfg=json.loads(CONFIG.read_text())
    # Synthetic events arrive 40 ms late and require another 20 ms lead.
    cfg['delay_seconds']={key:.05 for key in cfg['delay_seconds']}
    config=tmp_path/'late.synthetic.json';config.write_text(json.dumps(cfg))
    run(config,tmp_path/'late_mock')
    lines=[json.loads(s) for s in (tmp_path/'late_mock/events.synthetic.jsonl').read_text().splitlines()]
    current_ids={r['trial_id'] for r in lines if r['kind']=='trial' and r['linkage']=='current'}
    plans=[r for r in lines if r['kind']=='cue_plan' and r['trial_id'] in current_ids]
    assert plans and all(r['status']=='skipped' and r['reason']=='missed_deadline' for r in plans)
    receipts=[r for r in lines if r['kind']=='cue_receipt']
    assert receipts and not any(r['trial_id'] in current_ids for r in receipts)


def test_psychopy_toy_schedule_is_bounded_and_has_a_separate_replay_clock():
    pulses,current=toy_schedule(10,.5,'current');same,replay=toy_schedule(10,.5,'replay')
    assert pulses==same and current!=replay
    assert all(0<=t<10 for t in current+replay)


def test_presentation_refuses_live_mode_before_importing_gui_or_opening_files():
    with pytest.raises(ValueError,match='--simulate'):presentation(SimpleNamespace(simulate=False))
