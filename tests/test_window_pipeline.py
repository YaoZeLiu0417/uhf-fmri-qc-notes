import gzip
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('run_window_qc',SCRIPTS/'run_window_qc.py')
pipeline=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def test_artifact_union_does_not_double_count_overlapping_reasons():
    intervals=[{'onset_s':1.,'support_duration_s':5.},
               {'onset_s':3.,'support_duration_s':5.},
               {'onset_s':10.,'support_duration_s':2.}]
    assert pipeline.union_seconds(intervals)==9.


def test_unavailable_input_root_is_not_reported_as_missing_data(tmp_path):
    with pytest.raises(ValueError,match='unavailable'):
        pipeline.run(tmp_path/'manifest.json',tmp_path/'not_mounted',tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_private_export_pipeline_preserves_missing_channel_and_partial_window(tmp_path,monkeypatch):
    source=tmp_path/'source'
    directory=source/'sub-private'/'ses-test'/'func'
    directory.mkdir(parents=True)
    run_id='sub-private_ses-test_task-demo_run-1'
    t=np.arange(-5,40,.02)
    signal=np.round(2048+800*np.sin(2*np.pi*t))
    signal[(t>=27)&(t<33.2)]=4095
    path=directory/f'{run_id}_recording-cardiac_physio.tsv.gz'
    with gzip.open(path,'wt') as stream:
        np.savetxt(stream,signal,fmt='%d')
    path.with_name(path.name.removesuffix('.tsv.gz')+'.json').write_text(json.dumps({
        'Columns':['cardiac'],'SamplingFrequency':50.,'StartTime':-5.}))
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'runs':[{'run_id':run_id,'duration_seconds':35}]}))
    monkeypatch.setattr(pipeline,'plot_summary',lambda *_:None)
    summary=pipeline.run(manifest,source,tmp_path/'outputs')
    cardiac=summary['channels']['cardiac']
    respiration=summary['channels']['respiratory']
    assert cardiac['target_scan_seconds']==35
    assert cardiac['window_count']==2
    assert cardiac['window_seconds_by_state']['review']==35
    assert cardiac['artifact_union_support_seconds']<7
    assert respiration['missing_runs']==1
    assert respiration['window_seconds_by_state']['missing']==35
    assert 'sub-private' not in json.dumps(summary)
    assert str(tmp_path) not in json.dumps(summary)
    details=json.loads((tmp_path/'outputs/window_qc_details.private.json').read_text())
    assert [w['duration_s'] for w in details['runs'][0]['windows']]==[30,5]
