"""Synthetic checks of a delayed, incremental ROI-stream GLM contract."""
import numpy as np
import pytest
from scipy.stats import gamma
from experiments.interoception.roi_glm import IncrementalROIGLM, block_regressor


def model(**kw):
    return IncrementalROIGLM('synthetic_clock', **kw)


def feed(m, times, y, valid=None, motion=None, delayed_last=False):
    for i, (t, values) in enumerate(zip(times, y)):
        m.add_volume(i, float(t), values, 999. if delayed_last and i == len(times)-1 else float(t)+.2,
                     'synthetic_clock', valid=True if valid is None else bool(valid[i]),
                     motion=None if motion is None else motion[i])


def test_fractional_actual_onset_boxcar_convolution_matches_gamma_integral():
    times = np.arange(-2, 50, .37)
    onset, duration = 1.23, 7.61
    actual = block_regressor(times, onset, duration, .025)
    integral = lambda t: (gamma.cdf(np.clip(t, 0, 32), 6)-gamma.cdf(np.clip(t, 0, 32), 16)/6)
    expected = (integral(times-onset)-integral(times-onset-duration))/integral(32)
    assert np.allclose(actual, expected, atol=2e-5)
    assert np.all(actual[times < onset] == 0)
    assert np.all(actual[times >= onset+duration+32] == 0)


def test_incremental_refit_recovers_known_betas_and_stable_definition():
    m = model();m.add_block('a', 5.3, 10);m.add_block('b', 68.1, 10)
    times = np.arange(0, 150, 2.)
    x = np.column_stack([block_regressor(times, 5.3, 10), block_regressor(times, 68.1, 10),
                         np.ones(len(times)), times/150])
    coef = np.array([[1.2,.3],[-.4,.1],[10,12],[.2,-.1]])
    feed(m, times[:40], (x@coef)[:40])
    early = m.score('a', 80.)
    assert early['status']=='ok' and early['beta_difference']==pytest.approx(.9, abs=1e-9)
    for i in range(40,len(times)):
        m.add_volume(i,float(times[i]),(x@coef)[i],float(times[i])+.2,'synthetic_clock')
    late = m.score('a', 150.)
    assert late['definition_hash']==early['definition_hash']
    assert late['design_hash']!=early['design_hash'] and late['fit_revision']>early['fit_revision']
    assert late['variance'] < 1e-20
    assert m.score('b',150.)['beta_difference']==pytest.approx(-.5, abs=1e-9)


def test_future_arrival_and_unobserved_tail_do_not_create_a_score():
    m=model();m.add_block('a',5,10)
    times=np.arange(0,50,2.)
    y=np.column_stack([block_regressor(times,5,10),np.zeros(len(times))])
    feed(m,times,y,delayed_last=True)
    assert m.score('a',49.)['status']=='pending'
    assert m.score('a',999.)['status']=='ok'
    assert m.score('a',999.)['latest_input_available_time_s']==999.


def test_censored_extreme_volume_does_not_enter_fit():
    m=model();m.add_block('a',5,10)
    times=np.arange(0,80,2.);v=block_regressor(times,5,10)
    y=np.column_stack([v,np.zeros(len(v))]);y[8]=[1e12,-1e12]
    valid=np.ones(len(times),bool);valid[8]=False;feed(m,times,y,valid)
    result=m.score('a',80.)
    assert result['status']=='ok' and result['n_censored_volumes']==1
    assert result['beta_difference']==pytest.approx(1.)


def test_collinear_blocks_are_unestimable_and_low_df_is_pending():
    m=model();m.add_block('a',5,10);m.add_block('b',5,10)
    times=np.arange(0,80,2.);feed(m,times,np.zeros((len(times),2)))
    assert m.score('a',80.)['reason']=='rank_deficient_design'
    small=model();small.add_block('a',0,1)
    feed(small,[0,34,36,38],np.zeros((4,2)))
    assert small.score('a',40.)['status']=='pending'


def test_six_motion_terms_fit_and_paired_covariance_is_preserved():
    rng=np.random.default_rng(17);m=model(include_motion=True);m.add_block('a',5,10)
    times=np.arange(0,100,2.);mtn=rng.normal(size=(len(times),6));v=block_regressor(times,5,10)
    common=rng.normal(size=len(times))*.02+mtn@np.arange(6)*.01
    y=np.column_stack([common+v,common])
    feed(m,times,y,motion=mtn);result=m.score('a',100.)
    assert result['status']=='ok' and result['n_regressors']==9
    assert result['beta_difference']==pytest.approx(1.)
    assert result['roi_beta_variances'][0]>0 and result['variance']<1e-20


@pytest.mark.parametrize('bad',[{'volume_id':True},{'volume_id':-1},{'sample_time_s':float('nan')},
    {'available_time_s':-.1},{'clock_id':'unmapped'},{'valid':1},{'roi_values':[1,float('nan')]}])
def test_invalid_timing_clock_or_values_are_rejected(bad):
    args=dict(volume_id=0,sample_time_s=0.,roi_values=[1.,2.],available_time_s=.2,clock_id='synthetic_clock',valid=True)
    args.update(bad)
    with pytest.raises(ValueError):model().add_volume(**args)


def test_duplicate_or_reordered_volumes_and_underspecified_motion_fail():
    m=model();m.add_volume(1,0.,[1,2],.1,'synthetic_clock')
    with pytest.raises(ValueError):m.add_volume(1,2.,[1,2],2.1,'synthetic_clock')
    with pytest.raises(ValueError):m.add_volume(2,-1.,[1,2],2.1,'synthetic_clock')
    with pytest.raises(ValueError):m.add_volume(2,2.,[1,2],2.1,'synthetic_clock',motion=[0]*6)
    with pytest.raises(ValueError):model(include_motion=True).add_volume(0,0.,[1,2],.1,'synthetic_clock',motion=[0]*5)
    with pytest.raises(ValueError):model(hrf_tail_s=1)


def test_actual_offset_replaces_planned_boxcar_and_changes_fit_provenance():
    m=model();m.add_block('a',5.,20.)
    times=np.arange(0,100,2.);actual=block_regressor(times,5.,9.5)
    feed(m,times,np.column_stack([actual,np.zeros(len(times))]))
    planned=m.score('a',100.)
    updated=m.update_block_offset('a',14.5)
    result=m.score('a',100.)
    assert updated['duration_s']==9.5
    assert result['beta_difference']==pytest.approx(1.,abs=1e-9)
    assert planned['beta_difference']!=pytest.approx(1.,abs=1e-3)
    assert result['definition_hash']==planned['definition_hash']
    assert result['design_hash']!=planned['design_hash']
    assert result['block_offset_s']==14.5 and result['block_duration_s']==9.5


def test_later_actual_offset_requires_new_hrf_tail_observations():
    m=model();m.add_block('a',0.,1.)
    times=np.arange(0,40,2.);feed(m,times,np.zeros((len(times),2)))
    assert m.score('a',40.)['status']=='ok'
    m.update_block_offset('a',20.)
    result=m.score('a',40.)
    assert result['status']=='pending' and result['earliest_sample_time_for_score_s']==52.


@pytest.mark.parametrize('block_id,offset',[('unknown',10.),('a',5.),('a',4.),
    ('a',float('nan')),('a',True),('a',31.)])
def test_invalid_or_overlapping_actual_offsets_do_not_mutate_blocks(block_id,offset):
    m=model();m.add_block('a',5.,10.);m.add_block('b',30.,10.)
    before=[dict(b) for b in m.blocks]
    with pytest.raises(ValueError):m.update_block_offset(block_id,offset)
    assert m.blocks==before


def test_actual_offset_may_equal_next_block_onset():
    m=model();m.add_block('a',5.,10.);m.add_block('b',30.,10.)
    assert m.update_block_offset('a',30.)['duration_s']==25.
