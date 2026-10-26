"""A small desktop launcher for the explicitly synthetic PsychoPy presenter.

Run: python -m experiments.interoception.launcher
The operator canvas is the same renderer used for README screenshots.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from .contracts import ROOT
from .ui import FAMILIES, operator_card


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from PIL import ImageTk
    root=tk.Tk()
    root.title('Interoception · 实验工作台 · SIMULATION')
    root.geometry('1280x800');root.resizable(False,False)
    canvas=tk.Canvas(root,width=1280,height=800,highlightthickness=0)
    canvas.pack()
    available=importlib.util.find_spec('psychopy') is not None
    state=dict(family='heartbeat_attention',out=None,process=None,status='ready',view=None)
    hits={}
    logfile=None

    def draw():
        image,regions=operator_card(family=state['family'],view=state['view'],
            status=state['status'],psychopy_available=available,
            output_label='私有输出位置已选择' if state['out'] else '选择本机私有输出位置')
        state['image']=ImageTk.PhotoImage(image)
        canvas.delete('all');canvas.create_image(0,0,image=state['image'],anchor='nw')
        hits.clear();hits.update(regions)

    def output():
        chosen=filedialog.askdirectory(title='选择仓库外的私有输出父目录')
        if not chosen:return False
        parent=Path(chosen).resolve()
        if parent==ROOT or parent.is_relative_to(ROOT):
            messagebox.showerror('输出位置','请选择公开仓库外的目录。');return False
        state['out']=parent;draw();return True

    def start():
        nonlocal logfile
        if state['process'] is not None and state['process'].poll() is None:return
        if not available:
            messagebox.showinfo('需要 PsychoPy',
                '当前 Python 环境没有 PsychoPy。\n请在 PsychoPy 环境中运行本工作台。\n\n程序与 README 演示不代表现场设备已完成验证。')
            return
        if state['out'] is None and not output():return
        folder=state['out']/('presentation_demo_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        # The runner creates its own new folder, preventing silent overwrites.
        logpath=state['out']/(folder.name+'.launcher.private.log')
        logfile=logpath.open('x',encoding='utf-8')
        command=[sys.executable,'-m','experiments.interoception.run_presentation',
            '--simulate','--family',state['family'],'--out',str(folder)]
        try:
            state['process']=subprocess.Popen(command,cwd=ROOT,stdout=logfile,stderr=subprocess.STDOUT)
            state.update(status='running',run_folder=folder,view=None);draw()
        except OSError as exc:
            logfile.close();logfile=None
            messagebox.showerror('启动失败',str(exc))

    def click(event):
        if state['process'] is not None and state['process'].poll() is None:return
        for key,(x0,y0,x1,y1) in hits.items():
            if x0<=event.x<=x1 and y0<=event.y<=y1:
                if key.startswith('family:'):
                    state.update(family=key.split(':',1)[1],view=None,status='ready');draw()
                elif key=='output':output()
                elif key=='start':start()
                break

    def poll():
        nonlocal logfile
        process=state['process']
        if process is not None:
            status_file=state['run_folder']/'operator_status.private.json'
            try:
                info=json.loads(status_file.read_text(encoding='utf-8'))
                if info.get('is_synthetic') is True and info.get('view')!=state['view']:
                    state['view']=info['view'];draw()
            except (FileNotFoundError,json.JSONDecodeError,OSError):pass
            code=process.poll()
            if code is not None:
                state['status']='completed' if code==0 else ('aborted' if code==130 else 'error')
                state['process']=None
                if logfile:logfile.close();logfile=None
                draw()
        root.after(500,poll)

    def close():
        process=state['process']
        if process is not None and process.poll() is None:
            messagebox.showinfo('任务正在运行','请在参与者窗口按 Escape 结束，再关闭工作台。');return
        if logfile:logfile.close()
        root.destroy()

    canvas.bind('<Button-1>',click)
    root.bind('<Return>',lambda event:start())
    root.bind('<o>',lambda event:output())
    def select(number):
        process=state['process']
        if process is None or process.poll() is not None:
            state.update(family=tuple(FAMILIES)[number],view=None,status='ready');draw()
    for i in range(6):root.bind(str(i+1),lambda event,i=i:select(i))
    root.protocol('WM_DELETE_WINDOW',close)
    draw();poll();root.mainloop()


if __name__=='__main__':main()
