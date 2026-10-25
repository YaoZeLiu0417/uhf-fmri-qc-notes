import numpy as np
import pytest

from physio.beats import score
from physio.event_audit import event_pairs, window_pair_report


def test_pair_locations_match_existing_greedy_scorer():
    ref=np.array([1.,2.,3.,4.])
    det=np.array([.85,1.3,1.86,3.1,5.])
    pairs=event_pairs(ref,det)
    assert len(pairs)==score(ref*400,det*400,400)['n_matched']
    assert pairs.tolist()==[[0,0],[1,2],[2,3]]
    assert len(set(pairs[:,1]))==len(pairs)


def test_pair_crossing_display_boundary_is_not_discarded_or_counted_twice():
    ref=np.array([29.98]);det=np.array([30.04]);pairs=event_pairs(ref,det)
    left=window_pair_report(ref,det,pairs,0,30)
    right=window_pair_report(ref,det,pairs,30,60)
    assert left['matched_reference_events']==1 and left['matched_detection_events']==0
    assert right['matched_reference_events']==0 and right['matched_detection_events']==1
    assert left['matched_detection_fraction'] is None
    assert right['reference_marker_coverage'] is None
    assert left['median_detection_minus_marker_ms']==pytest.approx(60)


def test_empty_and_invalid_events_do_not_imply_perfect_agreement():
    pairs=event_pairs([],[])
    out=window_pair_report([],[],pairs,0,30)
    assert out['reference_marker_coverage'] is None
    assert out['median_detection_minus_marker_ms'] is None
    for events in ([1,1],[2,1],[-1,2],[np.nan]):
        with pytest.raises(ValueError):event_pairs(events,[])
