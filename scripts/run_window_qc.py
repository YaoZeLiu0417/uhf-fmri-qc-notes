"""Screen audited scan windows and save private details plus aggregate summaries.

This exploratory screen does not certify usable physiology or event accuracy.
The private run manifest supplies run_id and duration_seconds; audited BIDS
physiology supplies sample spacing and relative onset. No event logs are inferred.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physio.bids import RUN_ID
from physio.beats import evaluate_ppg
from physio.window_qc import window_qc
from scripts.plot_window_examples import render_examples

STATES = ('no_rule_flag', 'review', 'unusable', 'missing')
PROTOCOL = {
    'scope': 'Exploratory automatic scan-window screening; no_rule_flag is not validated usable time. Whole-log results were known before these rules were fixed.',
    'window_seconds': 30,
    'adc_boundary_fraction_review_above': .01,
    'constant_span_seconds_review_above': 5,
    'insufficient_variation_unique_values_below': 5,
    'adc_nominal_range': [0, 4095],
    'duration_accounting': 'Sum actual window durations, including final partial windows. Artifact support is separately unioned within each run; it is not whole flagged-window time.',
    'ppg_comparison': 'Run-local offline slope detector and bandpass peak detector from the same waveform and sample-hold preprocessing; neither is independent ECG truth. Detection is performed once per padded run, not reset in every 30-second window.',
    'event_count_disagreement_review_hint_above': .20,
    'event_count_disagreement_fraction': 'Absolute event-count difference divided by larger count; an exploratory review hint, not a main waveform-QC gate or an event-matching accuracy metric.',
    'example_selection': {
        'eligible': 'Fully covered 30-second cardiac windows after the first 30 scan seconds, at least 10 events from each detector; no nonfinite/out-of-range samples and not unusable.',
        'clear': 'Lowest ADC boundary fraction among no_rule_flag windows with event-count difference <=5%; tie by manifest/run/window order. Visual review remains required.',
        'clipping': 'Highest positive ADC boundary fraction among eligible windows; absent if none.',
        'disagreement': 'Largest positive detector count difference among eligible no_rule_flag windows with ADC boundary fraction <=1%; fallback to eligible positive-difference windows if absent.',
        'limits': 'Selected examples are descriptive extreme/clear candidates, not a random validation sample. Raw example waveforms stay private.'
    },
    'gain_timing': 'Exports have no embedded gain-message timestamps. Within-run gain transitions are not inferred or certified by this screen.',
    'task_event_alignment': 'Pending task event logs and verified trigger/clock mapping.',
}


def save_json(path, value):
    text = json.dumps(value, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def union_seconds(intervals):
    ranges = sorted((x['onset_s'], x['onset_s'] + x['support_duration_s'])
                    for x in intervals if x['support_duration_s'] > 0)
    total, last_start, last_end = 0., None, None
    for start, end in ranges:
        if last_start is None:
            last_start, last_end = start, end
        elif start <= last_end:
            last_end = max(last_end, end)
        else:
            total += last_end - last_start
            last_start, last_end = start, end
    return total + (last_end - last_start if last_start is not None else 0.)


def missing_windows(duration):
    return [{'window_index': i, 'onset_s': float(start), 'duration_s': float(min(30, duration-start)),
             'n_samples': 0, 'clip_fraction': None, 'longest_constant_span_s': None,
             'nonfinite_count': 0, 'out_of_range_count': 0, 'reasons': ['channel_export_missing'],
             'state': 'missing', 'coverage_seconds': 0.}
            for i, start in enumerate(np.arange(0, duration, 30.))]


def summarize(runs):
    summary = {'scope': PROTOCOL['scope'], 'run_definitions': len({x['run_id'] for x in runs}),
               'channel_run_candidates': len(runs), 'channels': {}, 'protocol': PROTOCOL,
               'manual_review_status': 'Pending. Automatically selected plots are review candidates; no window has human acceptance.'}
    for channel in ('cardiac', 'respiratory'):
        rows = [x for x in runs if x['channel'] == channel]
        present = [x for x in rows if x['source_present']]
        seconds = {state: sum(x['state_seconds'][state] for x in rows) for state in STATES}
        expected = sum(x['duration_s'] for x in rows)
        assert np.isclose(sum(seconds.values()), expected, atol=1e-7)
        windows = [w for x in rows for w in x['windows']]
        reasons = Counter(reason for w in windows for reason in w['reasons'])
        finite = sum(x.get('finite_sample_count', 0) for x in rows)
        summary['channels'][channel] = {
            'expected_runs': len(rows), 'present_runs': len(present), 'missing_runs': len(rows)-len(present),
            'target_scan_seconds': expected,
            'source_present_scan_seconds': sum(x['duration_s'] for x in present),
            'covered_seconds': sum(x['coverage_seconds'] for x in present),
            'window_count': len(windows),
            'window_counts_by_state': {state: sum(w['state'] == state for w in windows) for state in STATES},
            'window_seconds_by_state': seconds,
            'reason_window_counts_nonexclusive': dict(reasons),
            'artifact_union_support_seconds': sum(x['artifact_union_support_seconds'] for x in rows),
            'adc_boundary_sample_fraction': sum(x.get('clip_count', 0) for x in rows)/finite if finite else None,
            'maximum_constant_span_s_inside_scan': max((x['longest_constant_span_s'] for x in present), default=None),
            'windows_with_detector_count_difference_over_20pct': sum(
                (w.get('detector_count_difference_fraction') or 0) > .20 for w in windows),
            'event_disagreement_is_not_a_waveform_gate': True,
        }
    code = ['physio/window_qc.py', 'physio/beats.py', 'scripts/run_window_qc.py']
    summary['implementation_sha256'] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in code}
    return summary


def plot_summary(summary, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 5.5))
    labels = {'no_rule_flag':'No rule flag (not validated)', 'review':'Review required',
              'unusable':'Insufficient/invalid signal', 'missing':'No channel export'}
    colors = {'no_rule_flag':'#3278a8', 'review':'#d89b38', 'unusable':'#b94b54', 'missing':'#b8c2ce'}
    left = np.zeros(2)
    for state in STATES:
        values = np.array([summary['channels'][c]['window_seconds_by_state'][state]/60 for c in ('cardiac','respiratory')])
        ax.barh([1,0], values, left=left, height=.48, color=colors[state], label=labels[state])
        for y, start, value in zip([1,0], left, values):
            if value > 8:
                ax.text(start+value/2,y,f'{value:.1f} min',ha='center',va='center',fontsize=10,
                        color='white' if state in ('no_rule_flag','unusable') else '#192b3e')
        left += values
    ax.set(yticks=[1,0],yticklabels=['PPG','Respiration'],xlabel='Scan time, weighted by actual window duration (minutes)',ylim=(-.55,1.55))
    ax.spines[['top','right']].set_visible(False)
    ax.set_title('Physiological screening within 36 scan windows',loc='left',fontsize=18,pad=25)
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.22),ncol=2,frameon=False,fontsize=9)
    fig.text(.1,.05,'30-second windows; final partial windows retained. Automatic screening only.\n'
             'A flag applies to the whole window; artifact-sample duration is recorded separately. E-Prime alignment remains pending.',fontsize=9,color='#44556a')
    fig.subplots_adjust(left=.11,right=.98,top=.82,bottom=.32)
    fig.savefig(output,dpi=180,facecolor='white')
    plt.close(fig)


def run(manifest_path, physio_root, out):
    manifest_path, physio_root, out = map(lambda p: Path(p).resolve(), (manifest_path,physio_root,out))
    if not physio_root.is_dir():
        raise ValueError('Physiology root is unavailable or not a directory; this is not missing channel data')
    if out == physio_root or out.is_relative_to(physio_root):
        raise ValueError('Output must be separate from source physiology')
    if out == ROOT or out.is_relative_to(ROOT):
        raise ValueError('Private output must remain outside the public repository')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))['runs']
    ids = [r['run_id'] for r in manifest]
    if not ids or len(ids) != len({x.casefold() for x in ids}):
        raise ValueError('Run IDs must be unique')
    for item in manifest:
        if not RUN_ID.fullmatch(item['run_id']) or not np.isfinite(item['duration_seconds']) or item['duration_seconds'] <= 0:
            raise ValueError('Invalid run identifier or duration')
    names = ['window_qc_rules.json','window_qc_details.private.json','window_qc_summary.json',
             'example_selection.private.json','waveform_examples.private.png','window_qc_summary.png']
    if any((out/name).exists() for name in names):
        raise FileExistsError('Choose new output files; existing results are not overwritten')
    out.mkdir(parents=True,exist_ok=True)
    save_json(out/'window_qc_rules.json', PROTOCOL)
    runs, candidates = [], []
    for item in manifest:
        match = RUN_ID.fullmatch(item['run_id'])
        directory = physio_root/match['subject']
        if match['session']:
            directory /= match['session']
        for channel in ('cardiac','respiratory'):
            path = directory/'func'/f"{item['run_id']}_recording-{channel}_physio.tsv.gz"
            row = {'run_id':item['run_id'],'channel':channel,'duration_s':float(item['duration_seconds']),
                   'source_present':path.exists(),'missing_reason':None,'artifact_intervals':[],
                   'artifact_union_support_seconds':0.,'coverage_seconds':0.}
            if not path.exists():
                row.update(missing_reason='No channel export; inspect the prior export rejection report',
                           windows=missing_windows(row['duration_s']),adc_boundary_fraction=None,longest_constant_span_s=None)
            else:
                sidecar = path.with_name(path.name.removesuffix('.tsv.gz')+'.json')
                meta = json.loads(sidecar.read_text(encoding='utf-8'))
                if meta['Columns'] != [channel]:
                    raise ValueError('Sidecar channel does not match requested source')
                with gzip.open(path,'rt',encoding='ascii') as stream:
                    raw = np.loadtxt(stream,ndmin=1)
                fs, start = meta['SamplingFrequency'], meta['StartTime']
                screened = window_qc(raw,fs,start,row['duration_s'])
                row.update(windows=screened['windows'],artifact_intervals=screened['artifact_intervals'],
                           source_file=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           sampling_frequency=fs,start_time=start)
                row['artifact_union_support_seconds'] = union_seconds(row['artifact_intervals'])
                row['coverage_seconds'] = sum(w['coverage_seconds'] for w in row['windows'])
                row['finite_sample_count'] = sum(w['finite_sample_count'] for w in row['windows'])
                row['clip_count'] = sum(w['clip_count'] for w in row['windows'])
                row['adc_boundary_fraction'] = row['clip_count']/row['finite_sample_count'] if row['finite_sample_count'] else None
                row['longest_constant_span_s'] = max(w['longest_constant_span_s'] for w in row['windows'])
                if channel == 'cardiac' and np.isfinite(raw).all() and fs > 16 and np.unique(raw).size >= 5:
                    _, _, detector_a, detector_b = evaluate_ppg(raw,fs)
                    a, b = start+detector_a/fs, start+detector_b/fs
                    time = start+np.arange(len(raw))/fs
                    for w in row['windows']:
                        lo, hi = w['onset_s'],w['onset_s']+w['duration_s']
                        na,nb = int(np.count_nonzero((a>=lo)&(a<hi))),int(np.count_nonzero((b>=lo)&(b<hi)))
                        diff = abs(na-nb)/max(na,nb) if max(na,nb) else None
                        w.update(detector_a_events=int(na),detector_b_events=int(nb),detector_count_difference_fraction=diff)
                        if w['duration_s'] == 30 and np.isclose(w['coverage_seconds'],30,rtol=0,atol=1e-9) and lo >= 30 and min(na,nb)>=10 and w['state'] != 'unusable' and not w['nonfinite_count'] and not w['out_of_range_count']:
                            candidates.append({'run_id':row['run_id'],'source_file':str(path),'onset_s':lo,
                                               'clip_fraction':w['clip_fraction'],'state':w['state'],
                                               'difference':diff,'a_count':int(na),'b_count':int(nb)})
            row['window_count'] = len(row['windows'])
            row['state_seconds'] = {state:sum(w['duration_s'] for w in row['windows'] if w['state']==state) for state in STATES}
            assert np.isclose(sum(row['state_seconds'].values()),row['duration_s'])
            runs.append(row)
            print(f'Processed {len(runs)} channel/run candidates',flush=True)
    summary = summarize(runs)
    save_json(out/'window_qc_details.private.json', {'runs':runs,'summary':summary,'protocol':PROTOCOL})
    save_json(out/'window_qc_summary.json',summary)
    plot_summary(summary,out/'window_qc_summary.png')
    clear = [c for c in candidates if c['state']=='no_rule_flag' and c['difference']<=.05]
    clipping = [c for c in candidates if c['clip_fraction'] > 0]
    different = [c for c in candidates if c['difference'] > 0]
    disagreement = [c for c in different if c['state']=='no_rule_flag' and c['clip_fraction']<=.01]
    selected = []
    if clear:
        selected.append(dict(min(clear,key=lambda c:c['clip_fraction']),category='clear'))
    if clipping:
        selected.append(dict(max(clipping,key=lambda c:c['clip_fraction']),category='clipping'))
    if different:
        selected.append(dict(max(disagreement or different,key=lambda c:c['difference']),category='disagreement'))
    save_json(out/'example_selection.private.json',{
        'selected':selected,
        'missing_categories':sorted({'clear','clipping','disagreement'}-{x['category'] for x in selected}),
        'render_ready':len(selected)==3,
    })
    examples = []
    for selected_row in selected:
        path=Path(selected_row['source_file'])
        meta=json.loads(path.with_name(path.name.removesuffix('.tsv.gz')+'.json').read_text())
        with gzip.open(path,'rt',encoding='ascii') as stream:
            raw=np.loadtxt(stream,ndmin=1)
        fs,start=meta['SamplingFrequency'],meta['StartTime']
        _,_,da,db=evaluate_ppg(raw,fs)
        time=start+np.arange(len(raw))/fs
        lo,hi=selected_row['onset_s'],selected_row['onset_s']+30
        mask=(time>=lo)&(time<hi)
        examples.append(dict(category=selected_row['category'],time_s=time[mask],raw=raw[mask],fs=fs,start_time=lo,
            detector_a_times=(start+da/fs)[(start+da/fs>=lo)&(start+da/fs<hi)],
            detector_b_times=(start+db/fs)[(start+db/fs>=lo)&(start+db/fs<hi)],
            explanation=f"ADC boundary: {selected_row['clip_fraction']*100:.2f}%; event counts: A={selected_row['a_count']}, B={selected_row['b_count']}."))
    if len(examples) == 3:
        render_examples(examples,out/'waveform_examples.private.png')
    return summary


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--physio-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True,help='Private output directory; includes identifiers and waveform examples')
    args=parser.parse_args()
    run(args.manifest,args.physio_root,args.out)
