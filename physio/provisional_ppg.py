"""Parameter-stability PPG proposals, never independent event truth.

These are fixed signal-processing rules. AI can inspect their overlays, but
agreement among related filters is neither a calibrated probability nor ECG
validation. No labels from the existing A/B detectors or scanner enter here.
"""
import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks

from .beats import causal_hold_clipped
from .event_audit import event_pairs

PARAMETERS={
    'filter_low_hz':.5,'filter_high_hz_variants':[2.,3.,4.],
    'prominence_sd_variants':[.5,.8], 'filter_order':3,
    'minimum_peak_spacing_s':.4,'raw_peak_search_half_width_s':.08,
    'agreement_tolerance_s':.10,'uncertainty_margin_s':.20,
    'central_variant':{'filter_high_hz':3.,'prominence_sd':.5},
    'required_support_for_parameter_stability':6,
    'known_artifacts':'Existing stage-1 artifact supports are retained with the same 0.2 s preview margin; waveform states are not relaxed.',
    'minimum_intervals_for_window_rate':5,
    'interpretation':'Fixed exploratory proposals; six related parameter settings are not six independent annotators. Stability is not a correctness probability.',
}


def merge_intervals(ranges):
    result=[]
    for a,b in sorted(ranges):
        if b<=a:continue
        if result and a<=result[-1][1]:result[-1][1]=max(b,result[-1][1])
        else:result.append([float(a),float(b)])
    return result


def _raw_peaks(raw,peaks,half_width):
    return np.unique([max(0,p-half_width)+int(np.argmax(raw[max(0,p-half_width):min(len(raw),p+half_width+1)])) for p in peaks]).astype(int)


def propose(raw,fs):
    raw=np.asarray(raw)
    if raw.ndim!=1 or not np.isfinite(raw).all() or not np.isfinite(fs) or fs<=8:
        raise ValueError('Finite one-dimensional samples and fs > 8 Hz are required')
    if np.any((raw<0)|(raw>4095)):
        raise ValueError('Expected original 12-bit ADC values')
    if len(raw)<max(22,int(5*fs)) or len(np.unique(raw))<5:
        return {'status':'unresolved_short_or_low_variation','candidate_indices':np.array([],int),
                'support':np.array([],int),'stable':np.array([],bool),'variants':{},
                'disputed_indices':np.array([],int)}
    held,_=causal_hold_clipped(raw)
    variants={};half=max(1,int(round(PARAMETERS['raw_peak_search_half_width_s']*fs)))
    for high in PARAMETERS['filter_high_hz_variants']:
        filtered=sosfiltfilt(butter(3,[.5,high],btype='band',fs=fs,output='sos'),held)
        for prominence in PARAMETERS['prominence_sd_variants']:
            peaks,_=find_peaks(filtered,distance=max(1,int(.4*fs)),prominence=np.std(filtered)*prominence)
            variants[f'{high:g}Hz_{prominence:g}SD']=_raw_peaks(raw,peaks,half)
    central=variants['3Hz_0.5SD'];support=np.zeros(len(central),int)
    for events in variants.values():
        pairs=event_pairs(central/fs,events/fs,.1,.1)
        support[pairs[:,0]]+=1
    stable=(support==6)&(raw[central]>0)&(raw[central]<4095)
    stable_indices=central[stable]
    disputed=[int(p) for p in central[~stable]]
    for events in variants.values():
        pairs=event_pairs(stable_indices/fs,events/fs,.1,.1)
        used=set(pairs[:,1].tolist())
        disputed.extend(int(p) for i,p in enumerate(events) if i not in used)
    return {'status':'provisional_only','candidate_indices':central,'support':support,
            'stable':stable,'variants':variants,'disputed_indices':np.unique(disputed).astype(int)}


def scan_proposals(result,fs,start_time,duration,known_artifacts=()):
    if not np.isfinite([fs,start_time,duration]).all() or fs<=0 or duration<=0:
        raise ValueError('Invalid time mapping')
    indices=result['candidate_indices'];times=start_time+indices/fs
    inside=(times>=0)&(times<duration)
    unresolved=start_time+result['disputed_indices']/fs
    ranges=[(max(0,float(t)-.2),min(duration,float(t)+.2))
            for t in unresolved if -.2<t<duration+.2]
    ranges.extend((max(0,a['onset_s']-.2),min(duration,a['onset_s']+a['support_duration_s']+.2)) for a in known_artifacts)
    ranges=merge_intervals(ranges)
    if result['status']!='provisional_only' or not inside.any():ranges=[[0.,float(duration)]]
    events=[]
    for p,t,support,stable in zip(indices[inside],times[inside],result['support'][inside],result['stable'][inside]):
        context=any(a<=t<b for a,b in ranges)
        events.append({'sample_index_in_export':int(p),'time_s':float(t),'parameter_support':int(support),
                       'parameter_stable':bool(stable),'context_ambiguous':context,
                       'exploratory_candidate':bool(stable and not context),
                       'label_source':'fixed-rule automated proposal; not human or ECG truth'})
    return {'events':events,'uncertain_intervals_s':ranges,
            'uncertain_seconds':sum(b-a for a,b in ranges),'status':result['status']}


def window_report(scan,window):
    lo=window['onset_s'];hi=lo+window['duration_s']
    rows=[e for e in scan['events'] if lo<=e['time_s']<hi]
    ranges=[[max(lo,a)-lo,min(hi,b)-lo] for a,b in scan['uncertain_intervals_s'] if max(lo,a)<min(hi,b)]
    intervals=[]
    # Consecutive central proposals only: never bridge a discarded candidate.
    for a,b in zip(scan['events'][:-1],scan['events'][1:]):
        if not (lo<=a['time_s']<b['time_s']<hi):continue
        if not a['exploratory_candidate'] or not b['exploratory_candidate']:continue
        if any(x<b['time_s'] and y>a['time_s'] for x,y in scan['uncertain_intervals_s']):continue
        intervals.append(b['time_s']-a['time_s'])
    report={'central_candidates':len(rows),'parameter_stable_candidates':sum(e['parameter_stable'] for e in rows),
            'exploratory_candidates':sum(e['exploratory_candidate'] for e in rows),
            'uncertain_intervals_seconds_from_window_onset':ranges,
            'uncertain_seconds':sum(b-a for a,b in ranges),'retained_adjacent_intervals':len(intervals),
            'provisional_pulse_rate_bpm':None,'waveform_state':window['state'],
            'human_validated':False,'ecg_validated':False}
    if window['state']=='no_rule_flag' and len(intervals)>=5:
        report['provisional_pulse_rate_bpm']=float(60/np.median(intervals))
    return report
