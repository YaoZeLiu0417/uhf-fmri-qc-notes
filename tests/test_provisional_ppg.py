import numpy as np
import pytest

from physio.provisional_ppg import propose,scan_proposals,window_report,merge_intervals


def test_synthetic_ripple_proposals_are_bounded_and_keep_original_sample_indices():
    fs=100.;t=np.arange(0,60,1/fs)
    x=np.round(2048+600*np.cos(2*np.pi*t)+35*np.sin(2*np.pi*7*t))
    original=x.copy()
    out=propose(x,fs)
    np.testing.assert_array_equal(x,original)
    assert 55<=len(out['candidate_indices'])<=65
    assert np.all(np.diff(out['candidate_indices'])>0)
    assert np.all((out['candidate_indices']>=0)&(out['candidate_indices']<len(x)))
    assert out['stable'].sum()>=50
    scan=scan_proposals(out,fs,-5,50)
    assert all(0<=e['time_s']<50 for e in scan['events'])
    assert all(0<=a<b<=50 for a,b in scan['uncertain_intervals_s'])
    masked=scan_proposals(out,fs,-5,50,[{'onset_s':10,'support_duration_s':2}])
    assert any(a<=9.8 and b>=12.2 for a,b in masked['uncertain_intervals_s'])
    assert all(not e['exploratory_candidate'] for e in masked['events'] if 9.8<=e['time_s']<12.2)


def test_flat_signal_is_unresolved_instead_of_zero_verified_pulses():
    out=propose(np.full(1000,2048),100)
    scan=scan_proposals(out,100,0,10)
    assert scan['status']=='unresolved_short_or_low_variation'
    assert scan['uncertain_intervals_s']==[[0,10]]
    rep=window_report(scan,{'onset_s':0,'duration_s':10,'state':'no_rule_flag'})
    assert rep['provisional_pulse_rate_bpm'] is None and not rep['human_validated']
    with pytest.raises(ValueError):propose([1,np.nan],100)


def test_intervals_never_bridge_disputed_events_or_create_rate_on_warned_windows():
    events=[{'time_s':float(i),'parameter_stable':i!=3,'exploratory_candidate':i!=3} for i in range(1,10)]
    scan={'events':events,'uncertain_intervals_s':[[2.8,3.2]]}
    clean=window_report(scan,{'onset_s':0,'duration_s':10,'state':'no_rule_flag'})
    assert clean['retained_adjacent_intervals']==6
    assert clean['provisional_pulse_rate_bpm']==60
    warned=window_report(scan,{'onset_s':0,'duration_s':10,'state':'review'})
    assert warned['provisional_pulse_rate_bpm'] is None
    assert merge_intervals([[0,1],[.5,2],[3,4]])==[[0,2],[3,4]]
