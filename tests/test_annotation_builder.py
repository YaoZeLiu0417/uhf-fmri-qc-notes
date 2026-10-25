import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import numpy as np
import pytest

spec=importlib.util.spec_from_file_location('annotation_builder',Path(__file__).resolve().parents[1]/'scripts/build_ppg_annotation.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def inputs(tmp_path):
    folder=tmp_path/'exports';folder.mkdir()
    path=folder/'sub-hidden_task-demo_recording-cardiac_physio.tsv.gz'
    raw=np.arange(100)+2000
    with gzip.open(path,'wt') as stream:np.savetxt(stream,raw,fmt='%d')
    path.with_name(path.name.removesuffix('.tsv.gz')+'.json').write_text(json.dumps({
        'Columns':['cardiac'],'SamplingFrequency':10,'StartTime':-.5}))
    windows=tmp_path/'windows.json';windows.write_text(json.dumps({'runs':[{
        'run_id':'sub-hidden_task-demo','channel':'cardiac','source_present':True,
        'source_file':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}))
    audit=tmp_path/'audit.json';audit.write_text(json.dumps({'cases':[{
        'case_id':'C01','run_id':'sub-hidden_task-demo','window_index':0,'onset_s':1.5,
        'duration_s':3,'prior_workbook_sheet':'windows','prior_workbook_row':6}]}))
    return audit,windows,path


def test_builder_keeps_exact_samples_but_hides_identity_and_algorithm_events(tmp_path):
    audit,windows,path=inputs(tmp_path)
    out=tmp_path/'out';manifest=builder.build(audit,windows,out)
    page=(out/'PPG原始波形标注.private.html').read_text(encoding='utf-8')
    payload=json.loads(re.search(r'<script id="dataset" type="application/json">(.*?)</script>',page,re.S)[1])
    assert 'sub-hidden' not in page
    assert payload['cases'][0]['samples']==list(range(2020,2050))
    assert set(payload['cases'][0])=={'case_id','duration_s','sampling_frequency','first_sample_time_s','samples'}
    assert manifest['initial_human_annotations']==0 and not manifest['algorithm_event_arrays_included']
    assert (out/'case_mapping.private.json').exists()
    with pytest.raises(FileExistsError):builder.build(audit,windows,out)


def test_changed_export_is_rejected_before_output_creation(tmp_path):
    audit,windows,path=inputs(tmp_path)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Source changed'):builder.build(audit,windows,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_unsafe_case_identity_is_rejected(tmp_path):
    audit,windows,path=inputs(tmp_path)
    d=json.loads(audit.read_text());d['cases'][0]['case_id']='<img onerror=alert(1)>'
    audit.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='anonymous'):builder.build(audit,windows,tmp_path/'out')
