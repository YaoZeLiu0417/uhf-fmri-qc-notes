"""Draw proposed task timing and interface boundaries, without participant data.

Optional figure dependencies: matplotlib and seaborn.
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
import seaborn as sns

OUT=Path(__file__).resolve().parents[1]/'docs/assets'
C=dict(blue='#0070C0',red='#D94A3C',teal='#228B8D',ink='#252525',gray='#707070',line='#CFD9DF')
sns.set_theme(style='white',font='Arial',rc={'svg.fonttype':'path','pdf.fonttype':42,'lines.solid_capstyle':'round'})


def text(a,x,y,s,size=16,col='ink',bold=False,ha='left'):
    return a.text(x,y,s,fontsize=size,color=C[col],weight='bold' if bold else 'normal',ha=ha,va='center',linespacing=1.25)


def arrow(a,start,end,col='gray'):
    a.add_patch(FancyArrowPatch(start,end,arrowstyle='-|>',mutation_scale=12,lw=1.4,color=C[col],shrinkA=0,shrinkB=0))


def save(f,name):
    OUT.mkdir(exist_ok=True)
    f.canvas.draw()
    for a in f.axes:
        for t in a.texts:
            box=t.get_window_extent(f.canvas.get_renderer())
            assert box.x0>=0 and box.x1<=f.bbox.x1 and box.y0>=0 and box.y1<=f.bbox.y1,t.get_text()
    for ext in ['png','svg']:
        target=OUT/(name+'.'+ext);f.savefig(target,dpi=240,facecolor='white')
        if ext=='svg':target.write_text('\n'.join(line.rstrip() for line in target.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    plt.close(f)


def main():
    f=plt.figure(figsize=(12,5.2));a=f.add_axes([0,0,1,1]);a.set(xlim=(0,12),ylim=(0,5.2));a.axis('off')
    text(a,.35,4.75,'One proposed trial',22,bold=True)
    stages=[(.35,1.85,'Attention cue','1.5 s','gray'),(2.45,3.0,'Pulse and feedback','10 s','blue'),(5.7,1.65,'Synchrony','up to 4 s','red'),(7.65,1.65,'Confidence','up to 2 s','teal'),(9.6,2.0,'Fixation','2 / 4 / 6 s','gray')]
    for i,(x,w,name,duration,col) in enumerate(stages):
        a.add_patch(Rectangle((x,3.1),w,.15,fc=C[col],ec='none'));text(a,x+w/2,3.85,name,15,col,True,'center');text(a,x+w/2,2.65,duration,17,col,False,'center')
        if i<len(stages)-1:arrow(a,(x+w+.035,3.18),(stages[i+1][0]-.055,3.18))
    text(a,1.27,1.75,'Heartbeat\nor external attention',14,ha='center')
    text(a,3.95,1.75,'Current pulse\nor replay',14,ha='center')
    text(a,6.52,1.75,'0 to 100',16,'red',True,'center');text(a,8.47,1.75,'1 to 4',16,'teal',True,'center')
    text(a,10.6,1.75,'Balanced jitter',14,ha='center')
    text(a,6,.80,'Same report in every condition; unconfirmed responses stay missing',17,'blue',False,'center')
    text(a,6,.27,'Proposed pilot settings. Graphic spacing is schematic, not proportional to duration.',11,'gray',False,'center');save(f,'interoception-trial-timeline')
    f=plt.figure(figsize=(12,6));a=f.add_axes([0,0,1,1]);a.set(xlim=(0,12),ylim=(0,6));a.axis('off')
    text(a,.35,5.55,'Pulse-timed feedback and blockwise condition selection',21,bold=True)
    for x,head,body,col in [(2.05,'Live pulse input','Candidate event + quality\nEvent time + availability','blue'),(6,'Cue controller','Calibrated peripheral delay\nMeasured presentation','red'),(9.95,'Participant report','Synchrony + confidence\nSame probe across conditions','ink')]:
        text(a,x,4.62,head,18,col,True,'center');text(a,x,3.97,body,14,ha='center')
    arrow(a,(3.55,4.56),(4.38,4.56),'blue');arrow(a,(7.6,4.56),(8.39,4.56),'red')
    a.plot([.40,11.6],[3.20,3.20],c=C['line'],lw=.7)
    text(a,.40,2.73,'After a complete four-condition packet',17,'teal',True)
    for x,head,body in [(2.05,'Readout adapter','Behaviour first\nMRI when locally validated'),(6,'Selector interface','Choose the next delay\nfor a complete contrast'),(9.95,'Next packet','Heartbeat / external attention\nCurrent / replay feedback')]:
        text(a,x,2.03,head,17,'teal',True,'center');text(a,x,1.37,body,14,ha='center')
    arrow(a,(3.57,1.97),(4.43,1.97),'teal');arrow(a,(7.65,1.97),(8.42,1.97),'teal')
    text(a,6,.50,'Freeze task and readout before independent test blocks',17,'blue',False,'center')
    text(a,6,.14,'Proposed interfaces. The included selector is a balanced fallback, not Bayesian optimization.',10.5,'gray',False,'center');save(f,'interoception-two-loops')


if __name__=='__main__':main()
