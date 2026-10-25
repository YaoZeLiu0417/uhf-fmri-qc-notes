"""Render aggregate sensitivity summaries; no participant identifiers or raw traces."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def plot(summary_path,out):
    s=json.loads(Path(summary_path).read_text(encoding='utf-8'))
    out=Path(out)
    if out.exists():raise FileExistsError('Choose a new figure path')
    fig,(a,b)=plt.subplots(1,2,figsize=(13,5.4),gridspec_kw={'width_ratios':[1.1,1]})
    names=['Planned scan time','PPG export-covered time','Full rate-bearing windows','Retained interval support']
    values=[s['expected_scan_seconds']/60,s['source_present_scan_seconds']/60,s['prior_rate_window_seconds']/60,s['prior_rate_window_interval_support_seconds']/60]
    a.barh(names,values,color=['#cbd4db','#7896a9','#387c9f','#245775'])
    a.invert_yaxis();a.set_xlim(0,max(values)*1.23);a.set_xlabel('Minutes (different descriptive quantities)')
    for i,v in enumerate(values):a.text(v+3,i,f'{v:.2f}',va='center',fontsize=10)
    a.set_title('A  Window duration versus interval support',loc='left',fontsize=12)
    groups=[('All common windows','original_unflagged_windows'),('Selected disagreements','priority_windows'),('Other unflagged windows','other_unflagged_windows')]
    for i,(label,key) in enumerate(groups):
        g=s[key];q=g['rate_range_bpm']
        b.plot([q['median'],q['p95']],[i,i],color='#387c9f',lw=7,solid_capstyle='butt')
        b.scatter([q['median']],[i],color='#245775',s=30,zorder=3,label='Median' if i==0 else None)
        b.scatter([q['maximum']],[i],color='#c5822c',marker='D',s=42,label='Maximum' if i==0 else None)
        b.text(q['p95']+.5,i-.16,f"95th: {q['p95']:.2f}",fontsize=9,color='#245775')
        b.text(q['maximum']+.5,i+.13,f"Max: {q['maximum']:.2f}",fontsize=9,color='#956322')
    b.set_yticks(range(3),[f'{label}\n(n={s[key]["all_six_rates_available_windows"]})' for label,key in groups])
    b.set_ylim(2.6,-.6);b.set_xlim(-1,44);b.set_xlabel('Within-window rate range across six settings (bpm)')
    b.set_title('B  Related-setting sensitivity',loc='left',fontsize=12);b.legend(loc='lower right',frameon=False,fontsize=9)
    for ax in (a,b):ax.spines[['top','right']].set_visible(False);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('MRI PPG measurement | descriptive coverage and parameter sensitivity',fontsize=15,y=.98)
    fig.text(.025,.045,'Repeated windows are correlated; selected windows are nested in the full set. Percentiles are descriptive, not confidence intervals.',fontsize=9,color='#536776')
    fig.text(.025,.015,'Related-setting agreement and retained support time do not establish independent physiological accuracy or usable time.',fontsize=9,color='#536776')
    fig.tight_layout(rect=[.01,.11,.99,.93],w_pad=2.4)
    fig.savefig(out,dpi=170);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();plot(a.summary,a.out)
