"""Describe sensitivity of fixed related PPG settings without creating truth labels."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from physio.bids import RUN_ID
from physio.provisional_ppg import PARAMETERS,merge_intervals,propose


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+'\n')


def distribution(values):
    x=np.asarray([v for v in values if v is not None],float)
    keys=['minimum','p25','median','p75','p90','p95','maximum']
    q=np.percentile(x,[0,25,50,75,90,95,100]) if len(x) else [None]*7
    return {'n':len(x),**dict(zip(keys,[float(v) if v is not None else None for v in q]))}


def interval_report(times,keep,ranges,window):
    """Sum disjoint adjacent-pair support; never bridge rejected candidates."""
    times=np.asarray(times,float);keep=np.asarray(keep,bool)
    lo=window['onset_s'];hi=lo+window['duration_s']
    if times.ndim!=1 or keep.shape!=times.shape or not np.isfinite(times).all() or np.any(np.diff(times)<=0):
        raise ValueError('Candidate times must be finite, sorted and unique with one keep flag each')
    if not np.isfinite([lo,hi]).all() or hi<=lo:raise ValueError('Invalid window')
    if any(not np.isfinite([a,b]).all() or b<=a for a,b in ranges):raise ValueError('Invalid uncertainty range')
    left,right=np.searchsorted(times,[lo,hi]);t=times[left:right];k=keep[left:right]
    good=k[:-1]&k[1:]
    for a,b in ranges:good&=~((a<t[1:])&(b>t[:-1]))
    intervals=np.diff(t)[good]
    rate=float(60/np.median(intervals)) if window['state']=='no_rule_flag' and len(intervals)>=PARAMETERS['minimum_intervals_for_window_rate'] else None
    seconds=float(intervals.sum())
    return {'raw_peak_candidates':len(t),'retained_adjacent_intervals':len(intervals),
            'interval_support_seconds':seconds,'interval_support_fraction':seconds/window['duration_s'],
            'provisional_pulse_rate_bpm':rate}


def compare_settings(reports):
    rates=[r['provisional_pulse_rate_bpm'] for r in reports.values()]
    counts=[r['raw_peak_candidates'] for r in reports.values()]
    available=[v for v in rates if v is not None]
    median_count=float(np.median(counts)) if counts else 0
    return {'available_rate_settings':len(available),'all_settings_rate_available':bool(rates and len(available)==len(rates)),
            'rate_range_bpm':float(max(available)-min(available)) if rates and len(available)==len(rates) else None,
            'candidate_count_spread_pct':100*(max(counts)-min(counts))/median_count if median_count else None}


def group_summary(windows):
    common=[w for w in windows if w['comparison']['all_settings_rate_available']]
    return {'windows':len(windows),'all_six_rates_available_windows':len(common),
            'rate_range_bpm':distribution([w['comparison']['rate_range_bpm'] for w in common]),
            'candidate_count_spread_pct':distribution([w['comparison']['candidate_count_spread_pct'] for w in common]),
            'illustrative_rate_range_threshold_counts':{str(t):sum(w['comparison']['rate_range_bpm']<=t for w in common) for t in [2,5,10]},
            'rate_range_le_5_but_count_spread_gt_10_windows':sum(w['comparison']['rate_range_bpm']<=5 and w['comparison']['candidate_count_spread_pct']>10 for w in common)}


def run(windows_path,proposals_path,out):
    out=Path(out).resolve()
    if out==ROOT or out.is_relative_to(ROOT):raise ValueError('Private outputs must stay outside the repository')
    if out.exists():raise FileExistsError('Use a new output directory')
    initial_hashes={str(p):digest(p) for p in (windows_path,proposals_path)}
    original=read(windows_path);prior=read(proposals_path)
    rows=[r for r in original['runs'] if r['channel']=='cardiac']
    previous={r['run_id']:r for r in prior['runs']}
    if len(previous)!=len(prior['runs']) or len(rows)!=len(previous) or len({r['run_id'] for r in rows})!=len(rows) or {r['run_id'] for r in rows}!=set(previous):raise ValueError('Run definitions must agree uniquely')
    if PARAMETERS!=prior['summary']['parameters']:raise ValueError('Previously fixed parameters changed')
    if any(out.is_relative_to(Path(r['source_file']).resolve().parent) for r in rows if r['source_present']):raise ValueError('Output must be separate from source exports')
    out.mkdir(parents=True)
    save(out/'protocol.json',{'parameters':PARAMETERS,
        'comparison':'Each related setting separately uses original QC and known artifact supports, not the six-setting consensus uncertainty mask.',
        'rate_rule':'At least five retained adjacent within-window intervals; no rejected-candidate or artifact bridging; prior waveform state must be no_rule_flag.',
        'interval_support':'Sum of the retained adjacent-pair durations in prior rate-bearing windows; descriptive time support, not verified physiology.',
        'descriptive_thresholds':{'rate_range_bpm':[2,5,10],'candidate_count_spread_pct':10},
        'threshold_interpretation':'Illustrative exploratory summaries, not validated acceptance criteria. No parameter retuning or best-setting selection.',
        'population':'Repeated windows and settings are correlated; no population inference or independent event accuracy test.',
    })
    targets={(c['run_id'],c['window_index']) for c in prior['priority_cases']}
    runs=[];checks={'source_exports_rehashed':0,'central_candidate_arrays_reproduced':0,'variant_run_counts_reproduced':0,'prior_window_rates_and_interval_counts_reproduced':0}
    for row in rows:
        old=previous[row['run_id']]
        if row['source_present']!=old['source_present'] or row['duration_s']!=old['duration_s']:raise ValueError('Source presence or duration changed')
        result={'run_id':row['run_id'],'source_present':row['source_present'],'duration_s':row['duration_s'],'windows':[]}
        if not row['source_present']:
            result['status']='source_missing'
            runs.append(result);continue
        path=Path(row['source_file']);source_hash=digest(path)
        if source_hash!=row['source_sha256'] or source_hash!=old['source_sha256']:raise ValueError('Source changed')
        meta_path=path.with_name(path.name.removesuffix('.tsv.gz')+'.json');meta=read(meta_path)
        if meta['Columns']!=['cardiac'] or meta['SamplingFrequency']!=old['sampling_frequency'] or meta['StartTime']!=old['start_time']:raise ValueError('Cardiac time mapping changed')
        with gzip.open(path,'rt',encoding='ascii') as stream:raw=np.loadtxt(stream,ndmin=1)
        fs,start=meta['SamplingFrequency'],meta['StartTime'];generated=propose(raw,fs)
        if generated['status']!='provisional_only' or len(generated['variants'])!=6:raise ValueError('Six fixed settings required')
        streams={}
        for name,indices in generated['variants'].items():
            time=start+indices/fs;indices=indices[(time>=0)&(time<row['duration_s'])];time=start+indices/fs
            if len(indices)!=old['variant_scan_event_counts'][name]:raise ValueError('Variant run count changed')
            keep=(raw[indices]>0)&(raw[indices]<4095)
            streams[name]=(time,keep)
        central=generated['candidate_indices'];time=start+central/fs
        central=central[(time>=0)&(time<row['duration_s'])]
        if central.tolist()!=[e['sample_index_in_export'] for e in old['events']]:raise ValueError('Central candidate indices changed')
        ranges=merge_intervals([(max(0,a['onset_s']-.2),min(row['duration_s'],a['onset_s']+a['support_duration_s']+.2)) for a in row['artifact_intervals']])
        previous_times=[e['time_s'] for e in old['events']];previous_keep=[e['exploratory_candidate'] for e in old['events']]
        if len(row['windows'])!=len(old['windows']):raise ValueError('Window definitions changed')
        for w,pw in zip(row['windows'],old['windows']):
            if any(w[k]!=pw[k] for k in ('window_index','onset_s','duration_s')):raise ValueError('Window changed')
            if w['state']!=pw['waveform_state']:raise ValueError('Prior waveform state changed')
            prior_support=interval_report(previous_times,previous_keep,old['uncertain_intervals_s'],w)
            if prior_support['retained_adjacent_intervals']!=pw['retained_adjacent_intervals'] or prior_support['provisional_pulse_rate_bpm']!=pw['provisional_pulse_rate_bpm']:raise ValueError('Prior interval/rate not reproduced')
            reports={k:interval_report(t,keep,ranges,w) for k,(t,keep) in streams.items()}
            comparison=compare_settings(reports)
            result['windows'].append({'window_index':w['window_index'],'onset_s':w['onset_s'],'duration_s':w['duration_s'],'waveform_state':w['state'],
                'priority_case':(row['run_id'],w['window_index']) in targets,'prior_consensus_support':prior_support,'settings':reports,'comparison':comparison})
        result.update(source_sha256=source_hash,source_metadata_sha256=digest(meta_path),sampling_frequency=fs,start_time=start,
            variant_sample_indices_in_export={k:[int(p) for p in v if 0<=start+p/fs<row['duration_s']] for k,v in generated['variants'].items()})
        runs.append(result)
        checks['source_exports_rehashed']+=1;checks['central_candidate_arrays_reproduced']+=1;checks['variant_run_counts_reproduced']+=6;checks['prior_window_rates_and_interval_counts_reproduced']+=len(result['windows'])
        print(f'Checked {len(runs)} of {len(rows)} run definitions',flush=True)
    all_windows=[w for r in runs for w in r['windows']]
    unflagged=[w for w in all_windows if w['waveform_state']=='no_rule_flag']
    rate_windows=[w for w in all_windows if w['prior_consensus_support']['provisional_pulse_rate_bpm'] is not None]
    present=[r for r in runs if r['source_present']]
    large=[(r,w) for r in present for w in r['windows'] if w['comparison']['rate_range_bpm'] is not None and w['comparison']['rate_range_bpm']>5]
    summary={
        'scope':'Descriptive sensitivity of six fixed related settings; no independent physiological accuracy or validated usable time.',
        'expected_cardiac_runs':len(runs),'present_cardiac_runs':len(present),'missing_cardiac_runs':len(runs)-len(present),
        'participants_with_exports':len({RUN_ID.fullmatch(r['run_id'])['subject'] for r in present}),
        'visits_with_exports':len({(RUN_ID.fullmatch(r['run_id'])['subject'],RUN_ID.fullmatch(r['run_id'])['session']) for r in present}),
        'expected_scan_seconds':sum(r['duration_s'] for r in runs),
        'source_present_scan_seconds':sum(r['duration_s'] for r in present),'export_covered_windows':len(all_windows),
        'original_unflagged_windows':group_summary(unflagged),
        'priority_windows':group_summary([w for w in unflagged if w['priority_case']]),
        'other_unflagged_windows':group_summary([w for w in unflagged if not w['priority_case']]),
        'rate_range_gt_5_concentration':{'windows':len(large),'runs':len({r['run_id'] for r,w in large}),
            'participants':len({RUN_ID.fullmatch(r['run_id'])['subject'] for r,w in large}),
            'visits':len({(RUN_ID.fullmatch(r['run_id'])['subject'],RUN_ID.fullmatch(r['run_id'])['session']) for r,w in large}),
            'within_prior_selected_windows':sum(w['priority_case'] for r,w in large)},
        'prior_rate_windows':len(rate_windows),'prior_rate_window_seconds':sum(w['duration_s'] for w in rate_windows),
        'prior_rate_window_retained_intervals':sum(w['prior_consensus_support']['retained_adjacent_intervals'] for w in rate_windows),
        'prior_rate_window_interval_support_seconds':sum(w['prior_consensus_support']['interval_support_seconds'] for w in rate_windows),
        'prior_rate_window_support_fraction':distribution([w['prior_consensus_support']['interval_support_fraction'] for w in rate_windows]),
        'per_setting':{k:{'raw_peak_candidates':sum(len(r['variant_sample_indices_in_export'][k]) for r in present),
            'unflagged_window_rates_bpm':distribution([w['settings'][k]['provisional_pulse_rate_bpm'] for w in unflagged])} for k in present[0]['variant_sample_indices_in_export']} if present else {},
        'parameters':PARAMETERS,'human_annotations_created':0,'independent_accuracy_established':False,
        'support_time_interpretation':'Disjoint retained adjacent-pair support inside prior rate-bearing windows, not independently validated usable time.',
        'comparison_mask_interpretation':'Variant rate comparisons do not use the six-setting consensus uncertainty mask; they retain original QC and known artifacts independently.',
        'threshold_interpretation':'2/5/10 bpm and 10% count-spread are descriptive summaries, not acceptance criteria.',
    }
    if any(digest(p)!=h for p,h in initial_hashes.items()):raise ValueError('Analysis input changed during processing')
    checks.update(input_manifests_unchanged=True,missing_runs_unimputed=True,human_annotations_created=0,
        scope='Consistency and implementation checks, not event accuracy.',
        implementation_sha256={p:digest(ROOT/p) for p in ['scripts/analyze_ppg_sensitivity.py','physio/provisional_ppg.py']})
    summary['implementation_sha256']=checks['implementation_sha256']
    save(out/'sensitivity_details.private.json',{'runs':runs,'summary':summary,'input_sha256':initial_hashes})
    save(out/'sensitivity_summary.json',summary)
    save(out/'validation.json',checks)
    print(json.dumps(summary,indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows',type=Path,required=True)
    parser.add_argument('--proposals',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();run(args.windows,args.proposals,args.out)
