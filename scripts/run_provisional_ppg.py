"""Generate separate automated PPG pseudo-labels and exploratory rate candidates.

This does not populate the independent human annotation tool or validate
true heartbeats. Selected overlays can subsequently receive AI visual review.
"""
import argparse
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
from physio.bids import RUN_ID
from physio.provisional_ppg import PARAMETERS,propose,scan_proposals,window_report


def save(path,data):
    text=json.dumps(data,indent=2,allow_nan=False)+'\n'
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:stream.write(text)


def distribution(items):
    x=np.asarray([v for v in items if v is not None],float)
    return {'n':len(x),'minimum':float(x.min()) if x.size else None,
            'median':float(np.median(x)) if x.size else None,'maximum':float(x.max()) if x.size else None}


def plot_priority(cases,traces,out):
    from matplotlib.lines import Line2D
    handles=[Line2D([0],[0],color='#34434f',label='Raw PPG'),
             Line2D([0],[0],marker='o',ls='',color='#2677a2',label='Parameter-stable, outside marked ambiguity'),
             Line2D([0],[0],marker='x',ls='',color='#c27b25',label='Disputed or ambiguous central candidate'),
             Line2D([0],[0],lw=7,color='#f4dfb0',label='Marked ambiguity / known artifact context')]
    for page in range((len(cases)+3)//4):
        block=cases[page*4:page*4+4];fig,axes=plt.subplots(len(block),2,figsize=(15,3*len(block)),squeeze=False)
        fig.suptitle('Automated PPG proposals | exploratory pseudo-labels',fontsize=16,y=.992)
        fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.966),ncol=2,frameon=False,fontsize=9)
        for row,c in enumerate(block):
            time,raw,scan=traces[c['run_id']];lo=c['onset_s'];hi=lo+30
            for ax,left,right in [(axes[row,0],lo,hi),(axes[row,1],c['zoom_onset_s'],c['zoom_onset_s']+5)]:
                mask=(time>=left)&(time<right)
                for a,b in scan['uncertain_intervals_s']:
                    if max(left,a)<min(right,b):ax.axvspan(max(left,a)-left,min(right,b)-left,color='#f4dfb0',alpha=.6)
                ax.plot(time[mask]-left,raw[mask],color='#34434f',lw=.8)
                for stable,color,marker in [(True,'#2677a2','o'),(False,'#c27b25','x')]:
                    points=[e['time_s'] for e in scan['events'] if left<=e['time_s']<right and e['exploratory_candidate']==stable]
                    ax.scatter(np.asarray(points)-left,np.interp(points,time,raw),s=23,color=color,marker=marker,zorder=3)
                ax.set(xlim=(0,right-left),ylim=(-100,4200),yticks=[0,2048,4095],xlabel='Seconds from displayed segment onset')
                ax.grid(alpha=.12);ax.spines[['top','right']].set_visible(False)
            w=c['proposal'];axes[row,0].set_title(f"{c['case_id']} | central={w['central_candidates']}, parameter-stable={w['parameter_stable_candidates']}, exploratory={w['exploratory_candidates']}",loc='left',fontsize=10)
            axes[row,1].set_title('Five-second diagnostic zoom',loc='left',fontsize=10)
            axes[row,0].set_ylabel('PPG (uncalibrated ADC)')
        fig.text(.07,.012,'Fixed related filter/peak rules. No calibrated confidence, human truth or ECG validation. AI visual review is a separate step.',fontsize=9,color='#526270')
        fig.tight_layout(rect=[.01,.03,.99,.915],h_pad=2)
        target=out/f'proposals_{page+1:02d}.private.png';fig.savefig(target,dpi=160);plt.close(fig)
        for c in block:c['plot']=target.name


def run(windows_path,audit_path,out):
    out=Path(out).resolve()
    if out==ROOT or out.is_relative_to(ROOT):raise ValueError('Private pseudo-label outputs must remain outside the public repository')
    if out.exists():raise FileExistsError('Choose a new output directory')
    original=json.loads(Path(windows_path).read_text(encoding='utf-8'))
    audit=json.loads(Path(audit_path).read_text(encoding='utf-8'))
    targets={(c['run_id'],c['window_index']):c for c in audit['cases']}
    source_rows=[r for r in original['runs'] if r['channel']=='cardiac']
    if any(out.is_relative_to(Path(r['source_file']).resolve().parent) for r in source_rows if r['source_present']):raise ValueError('Output must be separate from source physiology')
    out.mkdir(parents=True)
    save(out/'generation_protocol.json',{
        'parameters':PARAMETERS,'label_source':'fixed signal-processing rules; AI-assisted visual review of selected overlays follows separately',
        'input_selection':'All available cardiac run exports; priority review uses prior selected disagreement windows.',
        'no_ground_truth':'Pseudo-labels are not independent human, ECG or hardware-timing references.',
        'rate_rule':'At least five adjacent central-candidate intervals whose endpoints survive parameter and ambiguity checks, within an original no_rule_flag window. No bridging discarded candidates.',
    })
    runs=[];priority=[];traces={}
    for row in source_rows:
        result={'run_id':row['run_id'],'source_present':row['source_present'],'duration_s':row['duration_s'],
                'label_source':'automated_fixed_rules','human_validated':False,'ecg_validated':False,'windows':[]}
        if not row['source_present']:
            result.update(status='source_missing',events=[],uncertain_intervals_s=[[0,row['duration_s']]])
            for w in row['windows']:
                result['windows'].append({'window_index':w['window_index'],'onset_s':w['onset_s'],'duration_s':w['duration_s'],
                    'status':'source_missing','central_candidates':None,'parameter_stable_candidates':None,'exploratory_candidates':None,
                    'provisional_pulse_rate_bpm':None,'waveform_state':'missing','human_validated':False,'ecg_validated':False})
        else:
            path=Path(row['source_file'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('A source changed after stage-1 checks')
            meta=json.loads(path.with_name(path.name.removesuffix('.tsv.gz')+'.json').read_text())
            if meta['Columns']!=['cardiac']:raise ValueError('Cardiac export required')
            with gzip.open(path,'rt',encoding='ascii') as stream:raw=np.loadtxt(stream,ndmin=1)
            fs,start=meta['SamplingFrequency'],meta['StartTime']
            proposals=propose(raw,fs)
            scan=scan_proposals(proposals,fs,start,row['duration_s'],row['artifact_intervals'])
            result.update(scan,source_sha256=row['source_sha256'],sampling_frequency=fs,start_time=start,
                          variant_scan_event_counts={k:int(np.count_nonzero((start+p/fs>=0)&(start+p/fs<row['duration_s']))) for k,p in proposals['variants'].items()})
            if any(key[0]==row['run_id'] for key in targets):traces[row['run_id']]=(start+np.arange(len(raw))/fs,raw,scan)
            for w in row['windows']:
                report=window_report(scan,w)
                report.update(window_index=w['window_index'],onset_s=w['onset_s'],duration_s=w['duration_s'],
                    original_A_count=w.get('detector_a_events'),original_B_count=w.get('detector_b_events'))
                result['windows'].append(report)
                key=(row['run_id'],w['window_index'])
                if key in targets:
                    c=targets[key]
                    priority.append({'case_id':c['case_id'],'run_id':row['run_id'],'window_index':w['window_index'],
                        'onset_s':w['onset_s'],'duration_s':w['duration_s'],'zoom_onset_s':c['zoom_onset_s'],
                        'previous_event_counts':c['event_counts'],'proposal':report,'ai_visual_review_status':'pending'})
        runs.append(result)
        print(f'Processed {len(runs)} cardiac run definitions',flush=True)
    priority.sort(key=lambda c:c['case_id'])
    if len(priority)!=len(targets):raise ValueError('Not all prior priority windows have source proposals')
    present=[r for r in runs if r['source_present']];windows=[w for r in present for w in r['windows']]
    events=[e for r in present for e in r['events']]
    available_rate=[w for w in windows if w['provisional_pulse_rate_bpm'] is not None]
    summary={
        'scope':'AI-assisted exploratory workflow using fixed-rule automated pseudo-labels. No independent reference accuracy or validated physiological rate is established.',
        'expected_cardiac_runs':len(runs),'present_cardiac_runs':len(present),'missing_cardiac_runs':len(runs)-len(present),
        'participants_with_exports':len({RUN_ID.fullmatch(r['run_id'])['subject'] for r in present}),
        'visits_with_exports':len({(RUN_ID.fullmatch(r['run_id'])['subject'],RUN_ID.fullmatch(r['run_id'])['session']) for r in present}),
        'source_present_scan_seconds':sum(r['duration_s'] for r in present),
        'missing_scan_seconds':sum(r['duration_s'] for r in runs if not r['source_present']),
        'central_candidates':len(events),'parameter_stable_candidates':sum(e['parameter_stable'] for e in events),
        'exploratory_candidates':sum(e['exploratory_candidate'] for e in events),
        'marked_ambiguity_seconds':sum(r['uncertain_seconds'] for r in present),
        'window_count_with_exports':len(windows),'windows_with_provisional_rate':len(available_rate),
        'provisional_rate_window_seconds':sum(w['duration_s'] for w in available_rate),
        'provisional_rate_bpm_distribution':distribution([w['provisional_pulse_rate_bpm'] for w in available_rate]),
        'priority_windows':len(priority),
        'priority_central_candidates':sum(c['proposal']['central_candidates'] for c in priority),
        'priority_parameter_stable_candidates':sum(c['proposal']['parameter_stable_candidates'] for c in priority),
        'priority_exploratory_candidates':sum(c['proposal']['exploratory_candidates'] for c in priority),
        'priority_marked_ambiguity_seconds':sum(c['proposal']['uncertain_seconds'] for c in priority),
        'parameters':PARAMETERS,'human_annotations_created':0,
        'ai_visual_review_status':'pending on selected overlays; other windows receive automated proposals only',
        'rate_time_interpretation':'Window time with an available provisional estimate, not independently validated usable time.',
        'support_interpretation':'Count of related parameter settings, not independent votes or correctness probability.',
    }
    summary['implementation_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
        ['physio/provisional_ppg.py','scripts/run_provisional_ppg.py','physio/beats.py','physio/event_audit.py']}
    plot_priority(priority,traces,out)
    save(out/'pseudo_labels.private.json',{'format':'provisional_ppg_v1','runs':runs,'priority_cases':priority,'summary':summary})
    save(out/'provisional_summary.json',summary)
    print(json.dumps(summary,indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.windows,args.audit,args.out)
