import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec=importlib.util.spec_from_file_location('sensitivity',Path(__file__).resolve().parents[1]/'scripts/analyze_ppg_sensitivity.py')
sensitivity=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensitivity)


def test_interval_support_is_not_window_duration_or_a_bridge_over_a_rejected_point():
    window={'onset_s':0,'duration_s':10,'state':'no_rule_flag'}
    out=sensitivity.interval_report(np.arange(1,10),[True,True,False,True,True,True,True,True,True],[],window)
    assert out['retained_adjacent_intervals']==6
    assert out['interval_support_seconds']==6 and out['interval_support_fraction']==.6
    assert out['provisional_pulse_rate_bpm']==60
    masked=sensitivity.interval_report(np.arange(1,10),np.ones(9,bool),[[2.8,3.2]],window)
    assert masked==out
    window['state']='review'
    assert sensitivity.interval_report(np.arange(1,10),np.ones(9,bool),[],window)['provisional_pulse_rate_bpm'] is None


def test_half_open_windows_do_not_double_count_boundary_events_and_short_windows_remain_unknown():
    times=np.arange(11)
    first=sensitivity.interval_report(times,np.ones(11,bool),[],{'onset_s':0,'duration_s':5,'state':'no_rule_flag'})
    second=sensitivity.interval_report(times,np.ones(11,bool),[],{'onset_s':5,'duration_s':5,'state':'no_rule_flag'})
    assert first['raw_peak_candidates']==second['raw_peak_candidates']==5
    assert first['interval_support_seconds']==second['interval_support_seconds']==4
    assert first['provisional_pulse_rate_bpm'] is None
    with pytest.raises(ValueError):sensitivity.interval_report([1,1],[True,True],[],{'onset_s':0,'duration_s':5})


def test_matching_median_rates_can_coexist_with_different_event_counts_and_missing_rates_stay_unknown():
    reports={str(i):{'raw_peak_candidates':30 if i<5 else 40,'provisional_pulse_rate_bpm':60} for i in range(6)}
    comparison=sensitivity.compare_settings(reports)
    assert comparison['rate_range_bpm']==0
    assert comparison['candidate_count_spread_pct']==pytest.approx(100/3)
    group=sensitivity.group_summary([{'comparison':comparison}])
    assert group['rate_range_le_5_but_count_spread_gt_10_windows']==1
    reports['0']['provisional_pulse_rate_bpm']=None
    assert sensitivity.compare_settings(reports)['rate_range_bpm'] is None
    assert sensitivity.distribution([])['median'] is None
