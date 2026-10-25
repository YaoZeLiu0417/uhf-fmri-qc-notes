"""Audit selected PPG disagreements with source scanner markers and fixed detectors.

All waveforms, run identifiers, event arrays and review plots remain private.
Only the aggregate summary is intended for publication after inspection.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from physio import load_pmu
from physio.beats import evaluate_ppg,score
from physio.bids import RUN_ID,onset_seconds
from physio.event_audit import event_pairs,window_pair_report

PROTOCOL={
 'selection':'Existing stage-1 cardiac windows with state=no_rule_flag and detector count difference >20%; no newly tuned detector parameters or timing correction.',
 'matching_window_seconds':[-.3,.6],
 'pairing':'Legacy earliest-available one-to-one rule, applied at run level. Reference-side and detection-side window counts are reported separately across boundaries.',
 'references':'5000 source physiological markers, from the same pulse-oximeter recording; not independent ECG events or MRI TTL.',
 'alignment':'SourceSliceStart/Stop and original sample indices; exported samples must exactly equal the indicated raw source slice. No estimated time shift is applied.',
 'context_check':'Compare unchanged detectors applied once to each padded run versus once to the complete source recording. These are diagnostic context checks, not external validation.',
 'zoom_selection':'Five-second subwindow with the largest absolute A/B event-count difference; first subwindow resolves ties. Selected for inspection, not random sampling.',
 'visual_review':'AI-assisted descriptions may be added separately. Independent human pulse adjudication and ECG validation remain pending.',
 'external_basis':'PPG detectors can target peaks or systolic upslopes: https://pmc.ncbi.nlm.nih.gov/articles/PMC9393905/ . This does not identify the correct events in these data.',
}


def save(path,value):
    content=json.dumps(value,indent=2,allow_nan=False)+'\n'
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:stream.write(content)


def values(events,lo,hi):
    return events[(events>=lo)&(events<hi)]


def distribution(items):
    x=np.array([v for v in items if v is not None],float)
    return {'n':len(x),'minimum':float(x.min()) if x.size else None,
            'median':float(np.median(x)) if x.size else None,'maximum':float(x.max()) if x.size else None}


def draw_axis(ax,time,raw,events,lo,hi):
    mask=(time>=lo)&(time<hi)
    ax.plot(time[mask]-lo,raw[mask],color='#37434c',lw=.8)
    for key,color,marker in [('A','#167f8a','o'),('B','#c36b34','x'),('M','#8051a6','v')]:
        points=values(events[key],lo,hi)
        ax.scatter(points-lo,np.interp(points,time,raw),s=19 if marker!='v' else 26,
                   marker=marker,facecolors='none' if marker=='o' else color,
                   edgecolors=color if marker!='x' else None,label=key,zorder=3)
    ax.set(xlim=(0,hi-lo),ylim=(-100,4200),yticks=[0,2048,4095])
    ax.grid(alpha=.12)
    ax.spines[['top','right']].set_visible(False)


def plot_cases(cases,plot_data,out):
    from matplotlib.lines import Line2D
    handles=[Line2D([0],[0],color='#37434c',lw=1,label='Raw PPG'),
        Line2D([0],[0],marker='o',markerfacecolor='none',markeredgecolor='#167f8a',ls='',label='A: slope'),
        Line2D([0],[0],marker='x',color='#c36b34',ls='',label='B: bandpass peaks'),
        Line2D([0],[0],marker='v',color='#8051a6',ls='',label='M: scanner markers')]
    for page in range((len(cases)+3)//4):
        block=cases[page*4:page*4+4]
        fig,axes=plt.subplots(len(block),2,figsize=(15,3.1*len(block)),squeeze=False)
        fig.suptitle('Selected PPG event audit | full windows and diagnostic zooms',fontsize=16,y=.992)
        fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.963),ncol=4,frameon=False)
        for row,case in enumerate(block):
            data=plot_data[case['run_id']]
            lo=case['onset_s'];hi=lo+case['duration_s']
            zoom=case['zoom_onset_s']
            draw_axis(axes[row,0],data['time'],data['raw'],data['events'],lo,hi)
            draw_axis(axes[row,1],data['time'],data['raw'],data['events'],zoom,zoom+5)
            counts=case['event_counts']
            axes[row,0].set_title(f"{case['case_id']} | A={counts['A']}, B={counts['B']}, M={counts['M']}",loc='left',fontsize=11)
            axes[row,1].set_title(f"Five-second zoom, starting {zoom-lo:.0f} s into window",loc='left',fontsize=10)
            axes[row,0].set_ylabel('PPG (uncalibrated ADC)')
            axes[row,0].set_xlabel('Seconds from window onset')
            axes[row,1].set_xlabel('Seconds from zoom onset')
        fig.text(.08,.012,'Same-sensor references; no ECG truth, latency claim or timing calibration. All plots are private review material.',fontsize=9,color='#526270')
        fig.tight_layout(rect=[.02,.03,.99,.925],h_pad=2.2)
        target=out/f'contact_{page+1:02d}.private.png'
        fig.savefig(target,dpi=160)
        plt.close(fig)
        for case in block:case['contact_plot']=target.name


def summarize(cases,source_rows):
    sums={key:sum(c['event_counts'][key] for c in cases) for key in ('A','B','M')}
    participants={RUN_ID.fullmatch(c['run_id'])['subject'] for c in cases}
    visits={(RUN_ID.fullmatch(c['run_id'])['subject'],RUN_ID.fullmatch(c['run_id'])['session']) for c in cases}
    result={'scope':'Selected-window exploratory PPG event audit; conditioned on prior disagreement selection, not population accuracy.',
        'selected_windows':len(cases),'selected_seconds':sum(c['duration_s'] for c in cases),
        'participants':len(participants),'visits':len(visits),'runs':len({c['run_id'] for c in cases}),
        'raw_source_recordings':len(source_rows),'event_counts':sums,'protocol':PROTOCOL,
        'count_pattern':dict(Counter('A_above_M' if c['event_counts']['A']>c['event_counts']['M'] else 'A_at_or_below_M' for c in cases)),
        'manual_event_truth_status':'Pending; no true/false heartbeat labels are assigned.'}
    for key in ('A','B'):
        rows=[c['marker_comparison'][key] for c in cases]
        nref=sum(r['reference_events'] for r in rows);ndet=sum(r['detected_events'] for r in rows)
        result[key+'_marker_comparison']={
            'reference_events':nref,'detected_events':ndet,
            'matched_reference_events':sum(r['matched_reference_events'] for r in rows),
            'matched_detection_events':sum(r['matched_detection_events'] for r in rows),
            'unmatched_reference_events':sum(r['unmatched_reference_events'] for r in rows),
            'unmatched_detection_events':sum(r['unmatched_detection_events'] for r in rows),
            'per_window_median_offset_ms':distribution([r['median_detection_minus_marker_ms'] for r in rows]),
            'per_window_matched_offset_iqr_ms':distribution([r['matched_offset_iqr_ms'] for r in rows]),
            'window_count_difference_to_M':distribution([c['event_counts'][key]-c['event_counts']['M'] for c in cases]),
            'run_vs_whole_record_count_delta':distribution([c['event_counts'][key]-c['whole_record_context_counts'][key] for c in cases]),
        }
    paths=['physio/event_audit.py','physio/beats.py','physio/siemens_pmu.py','scripts/audit_event_disagreements.py']
    result['implementation_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    return result


def run(windows_path,runs_path,out):
    windows_path,runs_path,out=map(lambda p:Path(p).resolve(),(windows_path,runs_path,out))
    if out==ROOT or out.is_relative_to(ROOT):raise ValueError('Keep private review material outside the public repository')
    if out.exists():raise FileExistsError('Choose a new output directory')
    detail=json.loads(windows_path.read_text(encoding='utf-8'))
    manifest={r['run_id']:r for r in json.loads(runs_path.read_text(encoding='utf-8-sig'))['runs']}
    targets=[];excel_row=6
    for row in detail['runs']:
        for w in row['windows']:
            if row['channel']=='cardiac' and w['state']=='no_rule_flag' and (w.get('detector_count_difference_fraction') or 0)>.20:
                targets.append((row,w,excel_row))
            excel_row+=1
    if not targets:raise ValueError('No windows match the fixed prior selection')
    if any(out.is_relative_to(Path(row['source_file']).parent) for row,_,_ in targets):raise ValueError('Output must be separate from source exports')
    raw_parents={(runs_path.parent/manifest[row['run_id']]['puls']).resolve().parent for row,_,_ in targets}
    if any(out==parent or out.is_relative_to(parent) for parent in raw_parents):raise ValueError('Output must be separate from raw source directories')
    out.mkdir(parents=True)
    save(out/'event_audit_protocol.json',PROTOCOL)
    sources={};source_rows=[];plot_data={};cases=[];checks=[]
    for row,w,excel_row in targets:
        rid=row['run_id']
        if rid not in plot_data:
            item=manifest[rid]
            source=(runs_path.parent/item['puls']).resolve()
            if source not in sources:
                rec=load_pmu(str(source))
                if rec.kind!='puls' or rec.fs_source!='mdh_endpoints':raise ValueError('An endpoint-timed PULS source is required')
                _,_,full_a,full_b=evaluate_ppg(rec.signal,rec.fs)
                sources[source]=(rec,full_a,full_b)
                source_rows.append({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'samples':len(rec.signal),'scanner_marker_count':len(rec.trigger_idx)})
            rec,full_a,full_b=sources[source]
            path=Path(row['source_file'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('Stage-1 source export changed')
            meta=json.loads(path.with_name(path.name.removesuffix('.tsv.gz')+'.json').read_text())
            with gzip.open(path,'rt',encoding='ascii') as stream:raw=np.loadtxt(stream,ndmin=1)
            low,high=meta['SourceSliceStart'],meta['SourceSliceStop']
            if not np.array_equal(raw,rec.signal[low:high]):raise ValueError('Export is not the specified source sample slice')
            fs,start=meta['SamplingFrequency'],meta['StartTime']
            if not np.isclose(fs,rec.fs,rtol=0,atol=1e-7):raise ValueError('Source/export clock estimate differs')
            expected_start=rec.footer['LogStartMDHTime']/1000+low/fs-onset_seconds(item['volume_start'])
            if not np.isclose(start,expected_start,rtol=0,atol=1e-6):raise ValueError('Manifest onset and sample-slice clock mapping differ')
            time=start+np.arange(len(raw))/fs
            _,_,a,b=evaluate_ppg(raw,fs)
            # Use original sample indices through the exact export slice; no clock-fit correction.
            marker_local=rec.trigger_idx[(rec.trigger_idx>=low)&(rec.trigger_idx<high)]-low
            duration=row['duration_s']
            events={'A':values(start+a/fs,0,duration),'B':values(start+b/fs,0,duration),'M':values(start+marker_local/fs,0,duration)}
            contexts={'A':start+(full_a-low)/fs,'B':start+(full_b-low)/fs}
            pairs={key:event_pairs(events['M'],events[key]) for key in ('A','B')}
            for key in ('A','B'):
                old=score(events['M']*fs,events[key]*fs,fs)
                assert len(pairs[key])==old['n_matched']
            plot_data[rid]={'time':time,'raw':raw,'events':events,'contexts':contexts,'pairs':pairs}
            checks.append({'run_id':rid,'source_slice_equal':True,'prior_source_hash_equal':True,'pair_counts_equal_legacy_score':True,
                           'manifest_clock_mapping_error_s':abs(start-expected_start)})
        data=plot_data[rid];lo=w['onset_s'];hi=lo+w['duration_s']
        counts={key:len(values(times,lo,hi)) for key,times in data['events'].items()}
        assert counts['A']==w['detector_a_events'] and counts['B']==w['detector_b_events']
        substarts=np.arange(lo,hi,5.)
        differences=[abs(len(values(data['events']['A'],s,s+5))-len(values(data['events']['B'],s,s+5))) for s in substarts]
        case={'case_id':f'C{len(cases)+1:02d}','run_id':rid,'window_index':w['window_index'],'onset_s':lo,'duration_s':w['duration_s'],
            'prior_workbook_sheet':'分窗明细','prior_workbook_row':excel_row,'event_counts':counts,
            'whole_record_context_counts':{key:len(values(times,lo,hi)) for key,times in data['contexts'].items()},
            'marker_comparison':{key:window_pair_report(data['events']['M'],data['events'][key],data['pairs'][key],lo,hi) for key in ('A','B')},
            'events_seconds_from_window_onset':{key:(values(times,lo,hi)-lo).tolist() for key,times in data['events'].items()},
            'zoom_onset_s':float(substarts[int(np.argmax(differences))]),'human_event_adjudication':None,'ai_visual_note':None}
        cases.append(case)
    plot_cases(cases,plot_data,out)
    summary=summarize(cases,source_rows)
    save(out/'event_audit_details.private.json',{'cases':cases,'sources':source_rows,'checks':checks,'summary':summary})
    save(out/'event_audit_summary.json',summary)
    save(out/'event_audit_validation.json',{'selected_case_count':len(cases),'stage1_count_reproduction':True,'source_slice_checks':len(checks),'all_source_slices_equal':True,'legacy_pair_counts_reproduced':True,'no_time_shift_applied':True,
                                         'maximum_manifest_clock_mapping_error_s':max(c['manifest_clock_mapping_error_s'] for c in checks)})
    print(json.dumps(summary,indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows',type=Path,required=True)
    parser.add_argument('--runs',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.windows,args.runs,args.out)
