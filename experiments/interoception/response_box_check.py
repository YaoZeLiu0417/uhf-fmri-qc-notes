"""Record response-box key names before mapping the available 1/2 panel.

Run in PsychoPy: python -m experiments.interoception.response_box_check
                --seconds 20 --out /private/new_keycode_check
No MRI trigger is generated; the result does not validate physical latency.
"""
import argparse
import json
from pathlib import Path
from .contracts import private_output


def run(args):
    if not 1<=args.seconds<=120:raise ValueError('Choose a short 1–120 second keycode check')
    from psychopy import visual,core
    from psychopy.hardware import keyboard
    out=private_output(args.out);out.mkdir(parents=True)
    win=visual.Window(size=(1000,680),color='black',units='height',checkTiming=False,
        title='Response-box mapping · operator check')
    kb=keyboard.Keyboard();clock=core.MonotonicClock();rows=[]
    title=visual.TextStim(win,text='1 / 2 面板按键核对',font='Microsoft YaHei',height=.045,pos=(0,.28),color='white')
    note=visual.TextStim(win,text='只操作可用面板的两个按键。\n非应答手保持指脉与报警球位置。',
        font='Microsoft YaHei',height=.029,pos=(0,.12),wrapWidth=1.35,color='white')
    value=visual.TextStim(win,text='等待按键',font='Microsoft YaHei',height=.04,pos=(0,-.12),color='white')
    foot=visual.TextStim(win,text='实验员 Escape 结束 · 自动结束后查看本机记录',font='Microsoft YaHei',height=.022,pos=(0,-.37),color='#AAAAAA')
    kb.clearEvents();kb.clock.reset()
    try:
        running=True
        while running and clock.getTime()<args.seconds:
            for key in kb.getKeys(waitRelease=False,clear=True):
                if key.name=='escape':running=False;break
                rows.append(dict(key_name=key.name,key_rt_s=key.rt,arrival_task_s=clock.getTime(),
                    physical_button_identity=None,physical_latency_validated=False))
                value.text='记录到键码：'+key.name
            for stim in (title,note,value,foot):stim.draw()
            win.flip()
    finally:win.close()
    report=dict(mode='operator_response_keycode_check',clock_basis='PsychoPy software clocks',
        events=rows,observed_key_names=sorted({r['key_name'] for r in rows}),
        mapping_verified=False,mri_trigger_generated=False,physical_latency_validated=False)
    (out/'response_keycodes.private.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seconds',type=int,default=20)
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    print(json.dumps(dict(observed_key_names=run(args)['observed_key_names']),ensure_ascii=False))
