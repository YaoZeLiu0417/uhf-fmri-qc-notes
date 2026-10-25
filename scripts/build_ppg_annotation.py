"""Build a self-contained private, raw-only PPG annotation page."""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def build(audit_path,windows_path,out):
    out=Path(out).resolve()
    if out==ROOT or out.is_relative_to(ROOT):raise ValueError('Private waveforms must remain outside the public repository')
    if out.exists():raise FileExistsError('Choose a new output directory')
    audit=json.loads(Path(audit_path).read_text(encoding='utf-8'))
    windows=json.loads(Path(windows_path).read_text(encoding='utf-8'))
    rows={r['run_id']:r for r in windows['runs'] if r['channel']=='cardiac' and r['source_present']}
    cases=[];mapping=[];loaded={}
    for item in audit['cases']:
        if not isinstance(item['case_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',item['case_id']):raise ValueError('Use a short anonymous case identifier')
        row=rows[item['run_id']];path=Path(row['source_file']).resolve()
        if out==path.parent or out.is_relative_to(path.parent):raise ValueError('Output must be separate from source exports')
        if path not in loaded:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('Source changed after window screening')
            meta=json.loads(path.with_name(path.name.removesuffix('.tsv.gz')+'.json').read_text())
            if meta.get('Columns')!=['cardiac'] or isinstance(meta.get('SamplingFrequency'),bool) or not np.isfinite(meta.get('SamplingFrequency',0)) or meta.get('SamplingFrequency',0)<=0:raise ValueError('A cardiac export with a positive sampling rate is required')
            with gzip.open(path,'rt') as stream:raw=np.loadtxt(stream,ndmin=1)
            if not np.isfinite(raw).all() or not np.equal(raw,np.rint(raw)).all() or np.any((raw<0)|(raw>4095)):
                raise ValueError('This tool requires original finite 12-bit integer ADC samples')
            loaded[path]=(raw,meta)
        raw,meta=loaded[path];fs=meta['SamplingFrequency'];times=meta['StartTime']+np.arange(len(raw))/fs
        onset=item['onset_s'];selected=np.flatnonzero((times>=onset)&(times<onset+item['duration_s']))
        if selected.size<2:raise ValueError('Window has insufficient samples')
        case={'case_id':item['case_id'],'duration_s':item['duration_s'],'sampling_frequency':fs,
              'first_sample_time_s':float(times[selected[0]]-onset),'samples':raw[selected].astype(int).tolist()}
        cases.append(case)
        mapping.append({'case_id':item['case_id'],'run_id':item['run_id'],'window_index':item['window_index'],
                        'onset_s':onset,'duration_s':item['duration_s'],'source_file':str(path),
                        'source_sha256':row['source_sha256'],'first_sample_index_in_export':int(selected[0]),
                        'sample_count':len(selected),'prior_workbook_sheet':item['prior_workbook_sheet'],
                        'prior_workbook_row':item['prior_workbook_row']})
    ids=[c['case_id'] for c in cases]
    if not cases or len(ids)!=len(set(ids)):raise ValueError('Case identifiers must be unique')
    payload={'schema_version':1,'selection_condition':'Previously selected PPG disagreement windows; not a random accuracy sample.', 'cases':cases}
    canonical=json.dumps(payload,separators=(',',':'),sort_keys=True).encode()
    payload['fingerprint']=hashlib.sha256(canonical).hexdigest()
    template=(ROOT/'scripts/ppg_annotation_template.html').read_text(encoding='utf-8')
    core=(ROOT/'web/ppg_annotation_core.js').read_text(encoding='utf-8')
    content=template.replace('__DATA_JSON__',json.dumps(payload,separators=(',',':')).replace('<','\\u003c')).replace('__CORE_JS__',core)
    out.mkdir(parents=True)
    (out/'PPG原始波形标注.private.html').write_text(content,encoding='utf-8')
    (out/'case_mapping.private.json').write_text(json.dumps({'dataset_fingerprint':payload['fingerprint'],'cases':mapping},indent=2)+'\n',encoding='utf-8')
    manifest={'schema_version':1,'dataset_fingerprint':payload['fingerprint'],'case_count':len(cases),
        'total_window_seconds':sum(c['duration_s'] for c in cases),'raw_samples_included':sum(len(c['samples']) for c in cases),
        'algorithm_event_arrays_included':False,'study_identifiers_in_viewer':False,'initial_human_annotations':0,
        'initial_human_completion_count':0,'offline_self_contained':True,
        'sample_selection':'Exact original samples at timestamps in [window onset, window end), with the actual first-sample offset retained.'}
    (out/'annotation_tool_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--windows',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.audit,args.windows,args.out),indent=2))
