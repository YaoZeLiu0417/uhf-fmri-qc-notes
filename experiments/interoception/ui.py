"""Shared, deterministic artwork for the launcher, PsychoPy cards and demos.

Participant stimulus fields are achromatic and identical across feedback
sources. Timing-critical cues are drawn natively by PsychoPy, not rasterized
on every frame. Pillow is needed only by this presentation layer.
"""
from functools import lru_cache
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont

INK = '#172735'
MUTED = '#647684'
BLUE = '#0074BA'
PAPER = '#F4F7F8'
LINE = '#DEE6EB'
FIELD = '#000000'
FAMILIES = {
    'heartbeat_attention': ('心跳注意', 'Heartbeat attention', '身体注意'),
    'respiration_attention': ('呼吸注意', 'Natural respiration', '身体注意'),
    'visual_rhythm': ('视觉节律', 'Visual rhythm', '外部注意'),
    'body_feedback_synchrony': ('身体与反馈', 'Body–feedback synchrony', '关联探针'),
    'gradcpt_standard': ('目标检测', 'GradCPT · standard', '外部控制'),
    'gradcpt_reversed': ('反转动作映射', 'GradCPT · reversed', '动作控制'),
}


@lru_cache(maxsize=64)
def font(size, bold=False):
    """Use installed fonts; never redistribute a system font in the repo."""
    candidates = ([
        'C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ])
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def text(draw, xy, value, size=20, fill=INK, bold=False, anchor='la'):
    draw.text(xy, str(value), font=font(size, bold), fill=fill, anchor=anchor)


def lines(draw, xy, value, size=24, fill=INK, gap=12, anchor='ma'):
    x, y = xy
    for i, line in enumerate(str(value).split('\n')):
        text(draw, (x, y+i*(size+gap)), line, size, fill, anchor=anchor)


def roundrect(draw, box, fill, radius=16, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def glyph(draw, xy, family, size=28, color=BLUE):
    """Small monochrome symbols; no imported icon library or decorative plots."""
    x, y = xy
    if family in ('heartbeat_attention', 'body_feedback_synchrony'):
        pts=[(0,.52),(.22,.52),(.33,.26),(.46,.80),(.60,.38),(.70,.52),(1,.52)]
        draw.line([(x+a*size,y+b*size) for a,b in pts], fill=color,width=2)
        if family=='body_feedback_synchrony':
            draw.arc((x-4,y-4,x+size+4,y+size+4),10,300,fill=color,width=2)
    elif family=='respiration_attention':
        pts=[(x+t*size/30,y+size*(.5+.25*math.sin(t/30*2*math.pi))) for t in range(31)]
        draw.line(pts,fill=color,width=2)
    elif family=='visual_rhythm':
        for i in range(3):
            z=x+4+i*size*.4
            draw.ellipse((z,y+size*.42,z+4,y+size*.58),fill=color)
    else:
        draw.rectangle((x+2,y+2,x+size-2,y+size-2),outline=color,width=2)
        if family=='gradcpt_reversed':
            draw.line((x+size*.25,y+size*.5,x+size*.75,y+size*.5),fill=color,width=2)
        else:
            draw.ellipse((x+size*.4,y+size*.4,x+size*.6,y+size*.6),fill=color)


def participant_card(view, size=(1280, 800), *, dynamic=True):
    """The actual raster card used by the presenter; no algorithm info.

    Demo provenance stays constant for every screen. Neither current/replay
    nor scores, PPG traces, trial countdowns or model confidence are shown.
    """
    image = Image.new('RGB', (1280, 800), FIELD)
    d = ImageDraw.Draw(image)
    phase = view.get('phase','instruction')
    white, soft = '#FFFFFF', '#E3E3E3'
    if view.get('is_synthetic', True):
        text(d,(38,28),'演示模式  ·  无真实生理或磁共振输入',15,soft)
    if phase=='task':
        if dynamic:
            kind=view.get('stimulus',{}).get('kind','fixation')
            active=view.get('stimulus',{}).get('active',False)
            if kind in ('feedback','feedback_ring','visual_rhythm','cue') and active:
                level=round(255*float(view.get('stimulus',{}).get('intensity',1.)))
                d.ellipse((614,374,666,426),fill=(level,level,level))
            elif kind.startswith('gradcpt') or kind=='abstract_scene':
                # Only the synthetic demonstration uses these placeholders.
                _abstract_scene(d,view.get('stimulus',{}),640,385)
            else:
                d.line((630,400,650,400),fill=white,width=2)
                d.line((640,390,640,410),fill=white,width=2)
    elif phase in ('synchrony','confidence'):
        rating=view.get('rating') or {}
        value=rating.get('value')
        question='刚才，视觉反馈与你的心跳同步吗？' if phase=='synchrony' else '你对刚才的判断有把握吗？'
        text(d,(640,242),question,32,white,anchor='ma')
        labels=('不同步','同步') if phase=='synchrony' else ('较没把握','较有把握')
        for key,x,label in zip((1,2),(430,850),labels):
            color=white if value in (None,key) else '#666666'
            text(d,(x,350),str(key),68,color,anchor='ma')
            text(d,(x,457),label,28,color,anchor='ma')
            d.line((x-95,513,x+95,513),fill=white if value==key else '#555555',width=3 if value==key else 1)
        hint='已记录，请等待' if rating.get('confirmed') else '按 1 或 2 选择一次；不能判断可不作答'
        text(d,(640,614),hint,21,soft,anchor='ma')
    elif phase=='fixation':
        d.line((630,400,650,400),fill=white,width=2)
        d.line((640,390,640,410),fill=white,width=2)
    else:
        headings={'instruction':'准备开始','trigger_wait':'请保持放松','complete':'本段已完成','aborted':'本段已停止'}
        text(d,(640,250),headings.get(phase,'准备开始'),42,white,bold=True,anchor='ma')
        instruction=view.get('instruction','')
        if phase=='trigger_wait': instruction='保持注视中央，等待任务开始。'
        elif phase=='complete': instruction='谢谢，请等待实验员的下一步指示。'
        elif phase=='aborted': instruction='请等待实验员。'
        lines(d,(640,345),instruction,27,white,gap=14)
        if phase=='instruction':text(d,(640,620),'按 1 或 2 继续',21,soft,anchor='ma')
        if phase=='trigger_wait':
            d.line((633,485,647,485),fill=white,width=2)
            d.line((640,478,640,492),fill=white,width=2)
    return image if size==(1280,800) else image.resize(size,Image.Resampling.LANCZOS)


def _abstract_scene(d, stimulus, x, y):
    """Explicitly unvalidated geometric demo, never GradCPT photographs."""
    target=stimulus.get('category',stimulus.get('target_category','city'))=='mountain'
    if target:
        d.line([(x-120,y+55),(x-30,y-60),(x+20,y+3),(x+63,y-47),(x+126,y+55)],fill='#ECECEC',width=5)
    else:
        for offset,h in [(-105,65),(-55,100),(0,80),(55,120)]:
            d.rectangle((x+offset,y+55-h,x+offset+35,y+55),outline='#ECECEC',width=3)


@lru_cache(maxsize=12)
def display_font(size):
    for path in ('C:/Windows/Fonts/segoeuil.ttf','/System/Library/Fonts/HelveticaNeue.ttc',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf'):
        if Path(path).exists():return ImageFont.truetype(path,size)
    return font(size)


@lru_cache(maxsize=4)
def volume_art(size=(650,570)):
    """Original projected parametric shell: a design motif, never a brain map.

    Perspective, depth shading and overlapping contours make a continuous
    volume. No subject, atlas or third-party illustration is used.
    """
    import numpy as np
    from PIL import ImageFilter
    w,h=size
    art=Image.new('RGB',size,'black');d=ImageDraw.Draw(art)
    curves=[]
    u=np.linspace(0,2*np.pi,260)
    for v in np.linspace(0,2*np.pi,96,endpoint=False):
        r=.66+.14*np.sin(3*u+.3)
        xyz=np.array([(1.55+r*np.cos(v))*np.cos(u),
                      (1.12+r*np.cos(v))*np.sin(u),
                      .92*r*np.sin(v)+.28*np.sin(2*u)])
        ax,ay,az=.92,-.5,-.25
        rx=np.array([[1,0,0],[0,np.cos(ax),-np.sin(ax)],[0,np.sin(ax),np.cos(ax)]])
        ry=np.array([[np.cos(ay),0,np.sin(ay)],[0,1,0],[-np.sin(ay),0,np.cos(ay)]])
        rz=np.array([[np.cos(az),-np.sin(az),0],[np.sin(az),np.cos(az),0],[0,0,1]])
        x,y,z=rz@ry@rx@xyz
        scale=5.8/(5.8-z)
        px=w*.49+x*scale*w*.204;py=h*.49-y*scale*w*.204
        for i in range(len(u)-1):
            t=float(np.clip((x[i]+1.4)/3.2,0,1))
            cyan=np.array([51,176,228]);pink=np.array([221,29,134])
            color=(1-t)*cyan+t*pink
            depth=float(np.clip((z[i]+1.8)/3.4,0,1))
            light=.12+.88*depth**1.7
            color=tuple(int(c*light) for c in color)
            curves.append((z[i],[(px[i],py[i]),(px[i+1],py[i+1])],color))
    for z,points,color in sorted(curves,key=lambda a:a[0]):
        d.line(points,fill=color,width=2 if z>.7 else 1)
    glow=art.filter(ImageFilter.GaussianBlur(15))
    return Image.blend(glow,art,.82)


def operator_card(*, family='heartbeat_attention', view=None, status='ready',
                  psychopy_available=None, output_label='选择本机私有输出位置', size=(1280,800)):
    """Actual Tk canvas. Editorial black field, one focal volume, line menus."""
    view=view or dict(phase='instruction',is_synthetic=True,instruction='请阅读本段指令。\n保持自然呼吸，准备开始。')
    image=Image.new('RGB',(1280,800),'black')
    image.paste(volume_art((650,570)),(630,68))
    d=ImageDraw.Draw(image)
    white,gray,cyan,pink='white','#A2A5AD','#33B0E4','#DD1D86'
    d.ellipse((49,38,74,63),outline=white,width=2)
    d.ellipse((61,38,86,63),outline=cyan,width=2)
    text(d,(103,37),'INTEROCEPTION',19,white)
    text(d,(103,65),'RESEARCH PLATFORM',10,gray)
    text(d,(750,44),'任务呈现',15,white)
    d.line((750,73,810,73),fill=pink,width=2)
    text(d,(861,44),'ROI 流  /  独立控制器',14,gray)
    text(d,(1218,45),'DEMO',13,cyan,anchor='ra')
    text(d,(54,137),'EXPERIMENT PLATFORM',11,cyan)
    d.text((49,170),'Interoception',font=display_font(76),fill=white)
    d.line((54,284,312,284),fill=pink,width=2)
    text(d,(54,315),'内感受实验工作台',28,white)
    text(d,(54,380),'任务呈现 · 生理时序 · 岛叶响应',16,gray)
    text(d,(54,457),'TASK LIBRARY',12,cyan)
    hits={}
    for i,(key,(cn,en,tag)) in enumerate(FAMILIES.items()):
        col,row=i%2,i//2
        x,y=54+col*295,491+row*47
        selected=key==family
        d.line((x,y+34,x+260,y+34),fill=pink if selected else '#33353B',width=2 if selected else 1)
        text(d,(x,y),f'0{i+1}',12,pink if selected else '#6D717B')
        text(d,(x+36,y-4),cn,18,white if selected else '#B8BAC2')
        if selected:text(d,(x+250,y-4),'↗',19,cyan,anchor='ra')
        hits['family:'+key]=(x,y-8,x+264,y+37)
    # A single participant field floats over the volume; no bento dashboard.
    d.rectangle((766,247,1228,548),fill='#14151A',outline='#62666E',width=1)
    image.paste(participant_card(view,(448,280)),(773,254))
    d=ImageDraw.Draw(image)
    text(d,(774,216),'PARTICIPANT VIEW',12,white)
    text(d,(1222,216),FAMILIES[family][0],14,white,anchor='ra')
    names={'instruction':'指令','trigger_wait':'等待触发','task':'任务呈现','synchrony':'同步感评分','confidence':'信心评分','fixation':'注视','complete':'已完成','aborted':'已停止'}
    text(d,(774,567),names.get(view.get('phase'),'就绪'),17,white)
    text(d,(1222,571),'逐搏答案不显示  ·  来源隐藏',12,gray,anchor='ra')
    environment='环境待核验' if psychopy_available is None else ('可用' if psychopy_available else '待安装')
    d.line((774,610,1222,610),fill='#363841')
    text(d,(774,631),'MRI / ROI    未连接',12,gray)
    text(d,(1002,631),'PPG / 呼吸    未连接',12,gray)
    text(d,(774,662),'PsychoPy    '+environment,12,gray)
    text(d,(1002,662),'v0.3    开发原型',12,gray)
    label={'ready':'就绪 · 合成输入','running':'运行中 · 合成输入','completed':'本段已完成','aborted':'本段已停止','error':'运行异常 · 查看本机日志'}.get(status,status)
    roundrect(d,(54,665,327,721),white,28)
    text(d,(81,681),'启动参与者演示',17,'black')
    d.ellipse((278,676,313,711),fill=pink)
    text(d,(296,682),'↗',19,white,anchor='ma')
    hits['start']=(54,665,327,721)
    text(d,(366,684),'选择输出位置',15,white)
    d.line((366,713,468,713),fill='#666A76')
    hits['output']=(357,668,480,722)
    text(d,(54,756),label+'  /  '+output_label[:24],12,gray)
    text(d,(1222,756),'ORIGINAL VISUAL MOTIF · NOT AN ANATOMICAL MAP',9,'#737886',anchor='ra')
    return (image if size==(1280,800) else image.resize(size,Image.Resampling.LANCZOS)),hits


def showcase(view, *, family='body_feedback_synchrony', size=(1600,1000)):
    """Documentation composition of the same native card renderer."""
    im=Image.new('RGB',(1600,1000),'black')
    im.paste(volume_art((760,666)),(840,5));d=ImageDraw.Draw(im)
    text(d,(66,47),'INTEROCEPTION  /  RESEARCH PLATFORM',15,'#33B0E4')
    d.text((62,91),'Interoception',font=display_font(76),fill='white')
    d.text((62,172),'in the scanner.',font=display_font(76),fill='white')
    d.line((66,283,337,283),fill='#DD1D86',width=2)
    text(d,(66,317),'从身体时间线，到可检验的脑响应。',25,'white')
    op,_=operator_card(family=family,view=view)
    im.paste(op.resize((880,550),Image.Resampling.LANCZOS),(66,393))
    d.rectangle((65,392,946,943),outline='#3A3B43',width=1)
    text(d,(1011,465),'PARTICIPANT VIEW',13,'white')
    participant=participant_card(view,(525,328));im.paste(participant,(1011,500))
    phase=view.get('phase','instruction')
    captions={'instruction':'清晰指令，只需 1 / 2 两键。','trigger_wait':'安静等待，由独立触发启动。','task':'必要刺激，无逐搏答案参照。','synchrony':'两键直接作答，固定时长。','confidence':'记录主观把握，独立于脑分数。','fixation':'固定背景，控制视觉变化。','complete':'完成与中止，都有明确状态。'}
    text(d,(1011,853),captions.get(phase,'必要刺激与明确响应。'),21,'white')
    text(d,(1011,898),'PsychoPy · ROI stream · Adaptive search',13,'#A2A5AD')
    text(d,(66,970),'SOFTWARE DEMO · Synthetic inputs · No scanner connected',12,'#A2A5AD')
    return im if size==(1600,1000) else im.resize(size,Image.Resampling.LANCZOS)
