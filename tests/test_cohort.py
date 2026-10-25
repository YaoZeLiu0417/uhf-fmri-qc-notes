import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('cohort', Path(__file__).resolve().parents[1] / 'scripts/evaluate_cohort.py')
cohort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cohort)


def test_repeated_visits_and_pooled_counts_are_not_independent_samples():
    recordings = [{'participant_id':'private-person','recording_id':'a','visit_id':'pre','puls':'a.puls'},
                  {'participant_id':'private-person','recording_id':'b','visit_id':'post','puls':'b.puls'}]
    details = []
    for n_ref, n_det, matched in [(10, 10, 10), (90, 100, 45)]:
        score = {'n_ref':n_ref, 'n_det':n_det, 'n_matched':matched,
                 'matching_window_seconds':[-.3,.6], 'sensitivity':matched/n_ref, 'ppv':matched/n_det}
        details.append({'participant_id':'private-person','channel':'puls',
                        'constant_signal':False,'sample_span_minutes':1,
                        'sampling_frequency':400,'fs_source':'mdh_endpoints','footer_complete':True,
                        'gain_message_count':0,'qc':{'verdict':'OK'},
                        'marker_comparison':score,'narrow_window_comparison':score})
    out = cohort.aggregate(details, recordings)
    assert out['participants'] == 1 and out['visits'] == 2
    assert out['offline_ppg_evaluation']['historical_window']['pooled_reference_recall'] == .55
    assert out['offline_ppg_evaluation']['historical_window']['pooled_detection_ppv'] == .5
    assert 'private-person' not in str(out)
    details[0]['fs_source'] = 'default'
    out = cohort.aggregate(details, recordings)
    assert out['recording_quality']['puls']['fallback_sampling_rate_recordings'] == 1
    assert out['recording_quality']['puls']['long_record_effective_hz']['n'] == 1


def test_duplicate_participant_visit_cannot_inflate_visit_count():
    with pytest.raises(ValueError, match='one unique'):
        cohort.validate_recordings([{'participant_id':'p','visit_id':'pre','recording_id':'a'},
                                    {'participant_id':'p','visit_id':'pre','recording_id':'b'}])
    with pytest.raises(ValueError, match='visit_id'):
        cohort.validate_recordings([{'participant_id':'p','recording_id':'a'}])


def test_empty_or_malformed_visit_sources_cannot_inflate_coverage():
    row = {'participant_id':'p','visit_id':'pre','recording_id':'a'}
    with pytest.raises(ValueError, match='at least one'):
        cohort.validate_recordings([row])
    for path in ('', '  ', 4):
        with pytest.raises(ValueError, match='nonempty strings'):
            cohort.validate_recordings([dict(row, puls=path)])
