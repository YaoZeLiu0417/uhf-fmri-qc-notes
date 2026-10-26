import copy
import json
from pathlib import Path
import numpy as np
import pytest
from experiments.interoception.contracts import fingerprint
from experiments.interoception.taskspace import load_taskspace
from experiments.interoception.session import NeuroadaptiveSession
from experiments.interoception.roi_glm import block_regressor
from experiments.interoception.simulate_neuroadaptive import run

SPACE=Path(__file__).resolve().parents[1]/'experiments/interoception/taskspace.synthetic.json'


def space():return load_taskspace(SPACE)


def feed(session,times,onset=None,duration=30.):
    for i,t in enumerate(times):
        h=0 if onset is None else float(block_regressor(np.array([t]),onset,duration)[0])
        session.add_volume(volume_id=i,sample_time_s=float(t),roi_values=[h,.2*h],
            available_time_s=float(t+.1),clock_id=session.space['clock_id'],
            roi_definition_id=session.space['roi_definition_id'],is_synthetic=True)


def test_site_template_does_not_silently_invent_geometry():
    with pytest.raises(ValueError,match='independently frozen'):load_taskspace(SPACE.with_name('taskspace.site_template.json'))


def test_site_input_cannot_relabel_toy_hyperparameters_as_calibrated(tmp_path):
    cfg=json.loads(SPACE.read_text(encoding='utf-8'));cfg.update(is_synthetic=False,status='site_stream_dry_run')
    p=tmp_path/'site.json';p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='independently frozen'):load_taskspace(p)
    cfg['optimizer_parameter_status']='independently_calibrated_frozen'
    p.write_text(json.dumps(cfg));assert load_taskspace(p)['is_synthetic'] is False


def test_definition_mutation_and_duplicate_commands_are_rejected():
    cfg=space();bad=copy.deepcopy(cfg);bad['conditions'][0]['coordinates'][0]+=.01
    with pytest.raises(ValueError,match='changed'):NeuroadaptiveSession(bad,'synthetic')
    s=NeuroadaptiveSession(cfg,'synthetic');command=s.propose(1)['command']
    assert s.propose(1)['status']=='awaiting_actual_block_start'
    altered=dict(command,condition_id='other')
    with pytest.raises(ValueError):s.begin_block(altered,2,30)
    s.begin_block(command,2,30)
    assert s.propose(100)['status']=='waiting_for_actual_block_end'
    with pytest.raises(ValueError):s.begin_block(command,3,30)


def test_actual_end_and_hrf_wait_are_required_before_selection():
    s=NeuroadaptiveSession(space(),'synthetic',budget=1);c=s.propose(0)['command']
    s.begin_block(c,20,30);feed(s,np.arange(0,83,2),20,30)
    assert s.propose(83)['status']=='waiting_for_actual_block_end'
    s.end_block(c['block_id'],50)
    assert s.propose(60)['status']=='waiting_for_eligible_readout'
    assert s.propose(83)['status']=='ready_to_freeze'
    with pytest.raises(ValueError):s.end_block(c['block_id'],51)


def test_freeze_uses_separate_glm_and_fixed_test_plan():
    cfg=space();s=NeuroadaptiveSession(cfg,'synthetic',budget=1);c=s.propose(0)['command']
    s.begin_block(c,20,30);s.end_block(c['block_id'],50);feed(s,np.arange(0,83,2),20,30)
    result=s.freeze(83);training=s.development_glm;pred=copy.deepcopy(s.optimizer.posterior())
    assert s.glm is not training and not s.glm.volumes
    cfg['fixed_test_plan'].reverse()  # external dictionary cannot change frozen session
    command=s.propose(84)['command']
    assert command['condition_id']==result['snapshot']['test_plan'][0]
    assert command['role']=='test'
    with pytest.raises(ValueError):s.optimizer.fit([])
    with pytest.raises(ValueError):s.add_volume(volume_id=99,sample_time_s=82,roi_values=[1,0],available_time_s=84,
        clock_id=s.space['clock_id'],roi_definition_id=s.space['roi_definition_id'],is_synthetic=True)
    s.begin_block(command,86,30);s.end_block(command['block_id'],116)
    feed(s,np.arange(84,149,2),86,30)
    assert s.optimizer.posterior()==pred and len(training.volumes)==42


def test_roi_or_synthetic_provenance_cannot_change():
    s=NeuroadaptiveSession(space(),'synthetic')
    data=dict(volume_id=0,sample_time_s=0.,roi_values=[0.,0.],available_time_s=.1,
         clock_id=s.space['clock_id'],roi_definition_id='different',is_synthetic=True)
    with pytest.raises(ValueError):s.add_volume(**data)
    data.update(roi_definition_id=s.space['roi_definition_id'],is_synthetic=False)
    with pytest.raises(ValueError):s.add_volume(**data)


def test_end_to_end_controller_updates_from_roi_volumes_and_then_freezes(tmp_path):
    cfg=json.loads(SPACE.read_text(encoding='utf-8'));cfg['conditions']=cfg['conditions'][:3]
    cfg['fixed_test_plan']=[r['condition_id'] for r in cfg['conditions']]
    cfg['optimizer']['burn_in']=2
    source=tmp_path/'small.json';source.write_text(json.dumps(cfg),encoding='utf-8')
    result=run(source,tmp_path/'session',seed=9,budget=3,runs=1)
    r=result['runs'][0]
    assert result['participants']==0 and r['development_blocks']==r['test_blocks']==3
    assert r['test_glm_separate_from_development'] and r['optimizer_frozen_during_test']
    assert len(r['profile'])==3
    rows=[json.loads(line) for line in (tmp_path/'session/synthetic_run_1.private.jsonl').read_text().splitlines()]
    suggestions=[v['response']['optimization'] for v in rows if v['response'].get('optimization')]
    assert suggestions and any(d['n_observations']>0 for d in suggestions)
    assert any(v['event']['kind']=='block_ended' for v in rows)
    assert all(v['response']['block']['ended'] is False for v in rows if v['response']['status']=='block_registered')
