"""Plot synthetic controller checks. No human data or Nature mask pixels."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns


def plot(summary_path,out):
    report=json.loads(Path(summary_path).read_text(encoding='utf-8'))
    if report.get('is_synthetic') is not True or report.get('participants')!=0:
        raise ValueError('This plotting script accepts synthetic software checks only')
    sns.set_theme(style='ticks',font='Arial',rc={'axes.spines.top':False,'axes.spines.right':False,
         'svg.fonttype':'path','pdf.fonttype':42,'axes.labelsize':12,'font.size':12})
    run=report['runs'][0];rows=run['profile'];n=len(rows);x=np.arange(n)
    fig,(a,b)=plt.subplots(2,1,figsize=(12,7.3),gridspec_kw={'height_ratios':[1.35,1]},layout='constrained')
    mean=np.array([r['predicted_mean'] for r in rows]);sd=np.array([r['predicted_sd'] for r in rows])
    observed=[r['independent_test_contrast'] for r in rows]
    a.fill_between(x,mean-sd,mean+sd,color='#0070C0',alpha=.14,label='GP posterior SD')
    a.plot(x,mean,c='#0070C0',lw=1.7,label='Frozen GP prediction')
    a.scatter(x,observed,facecolor='white',edgecolor='#D94A3C',s=44,lw=1.4,label='Separate synthetic test GLM',zorder=5)
    a.set_title('Predicted profile and independent synthetic test',loc='left',fontsize=17,pad=12)
    a.set_ylabel('Synthetic III minus IV contrast');a.axhline(0,c='#B9C2C7',lw=.8,ls='--')
    a.set_xticks([1,4,7,10,13,16],['Heartbeat\nattention','Respiratory\nattention','Visual\nrhythm','Body-feedback\nsynchrony','GradCPT\nstandard','GradCPT\nreversed'])
    a.tick_params(axis='x',length=0,labelsize=11);a.set_xlim(-.6,n-.4)
    for v in [2.5,5.5,8.5,11.5,14.5]:a.axvline(v,c='#DCE3E7',lw=.7)
    a.legend(frameon=False,ncol=3,fontsize=10,loc='upper right')
    ids=[r['condition_id'] for r in rows];chosen=[ids.index(c) for c in run['development_condition_ids']]
    b.plot(np.arange(1,len(chosen)+1),chosen,c='#228B8D',lw=1.4,marker='o',ms=5)
    b.axvspan(.5,5.5,fc='#ECEFF1',alpha=.7);b.text(3,.2,'Random burn-in',fontsize=11,ha='center',color='#666')
    b.set(xlabel='Development block',ylabel='Selected candidate index',yticks=[0,5,10,17],xlim=(.5,len(chosen)+.5),ylim=(-.8,n-.2))
    b.set_title('Each new ROI estimate updates the next condition',loc='left',fontsize=17,pad=10)
    fig.suptitle('Synthetic integration check of the neuroadaptive prototype',fontsize=20,weight='bold')
    fig.supxlabel('Artificial task coordinates and ROI signals. Zero participants. No hardware or neural-performance claim.',fontsize=11,color='#666666')
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(out,dpi=240)
    svg=out.with_suffix('.svg');fig.savefig(svg)
    svg.write_text('\n'.join(t.rstrip() for t in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();plot(a.summary,a.out)
