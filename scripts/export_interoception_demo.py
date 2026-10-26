"""Export a staged synthetic walkthrough from the actual presenter and UI.

This is a scripted documentation recording, never a human session or a test
of MRI, physiology, display latency, keyboard latency, or online performance.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from PIL import Image, ImageSequence, __version__ as pillow_version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FPS = 8
DURATION_S = 20
FAMILY = 'body_feedback_synchrony'
FRAME_SIZE = (960, 600)
TIMINGS = dict(instruction_s=1.5, task_s=8.0, synchrony_s=3.0,
               confidence_s=2.0, fixation_s=2.0)
SCRIPTED_ACTIONS = {
    1.5: '1',
    3.0: 'trigger',
    12.0: '2', 14.5: '2',
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def staged_views():
    """Run the same presentation state machine with explicit synthetic keys."""
    from experiments.interoception.presentation import TaskPresentation

    registry_path = ROOT / 'experiments/interoception/taskspace.synthetic.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    if registry.get('is_synthetic') is not True:
        raise ValueError('Documentation export accepts the synthetic registry only')
    condition = next(row for row in registry['conditions'] if row['family'] == FAMILY)
    flow = TaskPresentation(condition, mode='demo', clock_id='synthetic_task_monotonic',
                            timings=TIMINGS, seed=0)
    flow.start(0.0)
    views = []
    for frame in range(FPS * DURATION_S):
        t = frame / FPS
        view = flow.advance(t, action=SCRIPTED_ACTIONS.get(t))
        if view is None:
            view = flow.view(t)
        if view.get('is_synthetic') is not True:
            raise ValueError('Every exported frame must explicitly be synthetic')
        # Detach snapshots from mutable state before advancing to the next frame.
        views.append(json.loads(json.dumps(view, ensure_ascii=False, allow_nan=False)))
    phases = {view['phase'] for view in views}
    required = {'instruction', 'trigger_wait', 'task', 'synchrony', 'confidence',
                'fixation', 'complete'}
    if not required.issubset(phases):
        raise RuntimeError(f'Walkthrough missed presenter phases: {sorted(required - phases)}')
    return views, registry_path


def save_gif(frames, path):
    """Preserve 20 s despite GIF's 10 ms timing quantization at nominal 8 fps."""
    durations = [round((i + 1) * 100 / FPS) * 10 - round(i * 100 / FPS) * 10
                 for i in range(len(frames))]
    for colors in (128, 64, 32):
        palette = frames[0].quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
        indexed[0].save(path, save_all=True, append_images=indexed[1:], duration=durations,
                        loop=0, optimize=True, disposal=1)
        if path.stat().st_size <= 8_000_000:
            break
    else:
        raise RuntimeError('GIF exceeds the requested 8 MB limit')
    with Image.open(path) as gif:
        actual_duration_ms = sum(frame.info.get('duration', 0) for frame in ImageSequence.Iterator(gif))
        encoded_frames = gif.n_frames
    if actual_duration_ms != DURATION_S * 1000:
        raise RuntimeError(f'GIF duration changed during encoding: {actual_duration_ms} ms')
    return dict(bytes=path.stat().st_size, encoded_frames=encoded_frames,
                duration_ms=actual_duration_ms, palette_colors=colors,
                timing_quantum_ms=10,
                source_frame_timing='120/130 ms quantization; cumulative duration preserved')


def save_mp4(frames, path, ffmpeg):
    """Feed RGB frames directly to the optional local FFmpeg executable."""
    ffmpeg = Path(ffmpeg).resolve(strict=True)
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y',
               '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{FRAME_SIZE[0]}x{FRAME_SIZE[1]}', '-r', str(FPS),
               '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
               '-crf', '23', '-preset', 'medium', '-movflags', '+faststart', str(path)]
    # A temporary stderr file avoids deadlocks without retaining another full
    # raw-video copy in memory. No shell or network is involved.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=errors, shell=False)
        try:
            for frame in frames:
                process.stdin.write(frame.convert('RGB').tobytes())
            process.stdin.close()
            returncode = process.wait()
        except BaseException:
            process.kill()
            process.wait()
            raise
        errors.seek(0)
        if returncode:
            raise RuntimeError('FFmpeg failed: ' + errors.read().decode('utf-8', errors='replace'))
    return dict(codec='H.264', pixel_format='yuv420p', fps=FPS,
                frames=len(frames), duration_s=len(frames) / FPS,
                ffmpeg_executable_sha256=sha256(ffmpeg), bytes=path.stat().st_size)


def write_gallery(out, has_mp4):
    exhibits = [
        ('participant-instruction.png', '01', '准备。', '明确注意目标，再进入任务。'),
        ('participant-task.png', '02', '观察。', '必要的实验线索，不叠加逐搏答案参照。'),
        ('participant-rating.png', '03', '判断。', '实际状态机驱动的量尺；此处的按键由脚本模拟。'),
        ('operator.png', '04', '控制。', '操作者工作台，呈现参与者之外的任务与接口状态。'),
    ]
    gallery = '\n'.join(
        f'<figure class="exhibit"><figcaption><span class="number">{number}</span>'
        f'<h3>{html.escape(title)}</h3><p>{html.escape(note)}</p></figcaption>'
        f'<a href="{name}" aria-label="打开完整尺寸：{html.escape(title)}">'
        f'<img loading="lazy" src="{name}" alt="{html.escape(title + note)}" width="1280" height="800"></a></figure>'
        for name, number, title, note in exhibits)
    video = ('<video controls playsinline preload="metadata" poster="hero.png" '
             'aria-label="20 秒合成程序流程" aria-describedby="walkthrough-note">'
             '<source src="walkthrough.mp4" type="video/mp4"></video>' if has_mp4 else
             '<picture><source media="(prefers-reduced-motion: reduce)" srcset="hero.png">'
             '<img src="walkthrough.gif" alt="20 秒合成界面演示" width="960" height="600"></picture>')
    document = f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>Interoception · 程序界面演示</title>
<style>
*{{box-sizing:border-box}}html{{background:#050505;color:#f4f4f1}}body{{margin:0;font:16px/1.65 Arial,"Microsoft YaHei",sans-serif}}
a{{color:inherit;text-underline-offset:6px}}a:hover{{color:#7ae6f0}}a:focus-visible,video:focus-visible{{outline:3px solid #7ae6f0;outline-offset:8px}}
.skip{{position:absolute;left:24px;top:-90px;background:#fff;color:#000;padding:12px 20px;z-index:10}}.skip:focus{{top:20px}}
header,main,footer{{width:min(1440px,100%);margin:auto}}header{{display:flex;justify-content:space-between;align-items:center;padding:32px 4vw;font-size:12px;letter-spacing:.13em}}
header a{{text-decoration:none}}header .label{{color:#aaa}}.cover{{margin:0}}img,video{{display:block;width:100%;height:auto}}.cover img{{max-height:calc(100vh - 84px);object-fit:contain;background:#050505}}
section{{padding:110px 4vw 0}}.section-heading{{display:flex;justify-content:space-between;gap:48px;align-items:end;margin-bottom:38px}}
h1,h2,h3,p{{margin:0}}h1{{font-size:clamp(44px,6.7vw,100px);font-weight:400;letter-spacing:-.055em;line-height:1.05}}h2{{font-size:clamp(36px,5.1vw,72px);font-weight:400;letter-spacing:-.045em;line-height:1.08}}
.eyebrow,.number{{font-size:12px;letter-spacing:.16em;color:#83e4ee}}.eyebrow{{margin-bottom:23px}}.section-heading p{{max-width:330px;color:#a9a9a9;font-size:15px;line-height:1.85}}
.screening{{margin:0}}.screening video,.screening picture{{background:#111;width:100%}}.screening figcaption{{display:flex;justify-content:space-between;gap:35px;margin-top:23px;color:#a9a9a9;font-size:13px}}
.downloads{{display:flex;gap:25px;flex-wrap:wrap}}.exhibit{{margin:75px 0 0}}.exhibit figcaption{{display:flex;gap:25px;align-items:baseline;margin-bottom:24px}}
h3{{font-size:34px;font-weight:400;letter-spacing:-.03em}}.exhibit figcaption p{{color:#aaa;margin-left:auto;max-width:460px;font-size:15px}}
.exhibit a{{display:block}}.exhibit img{{background:#000000}}footer{{padding:100px 4vw 45px}}.provenance{{border-top:1px solid #303030;padding-top:25px;display:flex;justify-content:space-between;gap:45px;color:#a7a7a7;font-size:13px}}
.provenance p{{max-width:680px}}.provenance a{{white-space:nowrap}}.sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
@media(max-width:720px){{header{{padding:24px 6vw}}header .label{{display:none}}section{{padding:72px 6vw 0}}.section-heading{{display:block;margin-bottom:30px}}.section-heading p{{margin-top:25px;max-width:100%}}.cover img{{max-height:none}}.screening figcaption,.provenance{{display:block}}.downloads{{margin-top:18px}}.exhibit{{margin-top:55px}}.exhibit figcaption{{flex-wrap:wrap;gap:12px 20px}}.exhibit figcaption p{{flex-basis:100%;margin-left:0;max-width:100%}}footer{{padding:75px 6vw 35px}}.provenance a{{display:inline-block;margin-top:20px}}}}
</style><body><a class="skip" href="#walkthrough">跳到程序演示</a>
<header><a href="#top" aria-label="回到页面顶部">INTEROCEPTION</a><span class="label">SOFTWARE EXHIBITION · SYNTHETIC DEMO</span><a href="provenance.synthetic.json">来源记录 ↗</a></header>
<main id="top"><h1 class="sr-only">内感受实验工作台 · 程序演示</h1>
<figure class="cover"><img src="hero.png" alt="内感受实验工作台总览，由本项目共享渲染器生成" width="1600" height="1000"></figure>
<section id="walkthrough" aria-labelledby="walkthrough-heading">
<div class="eyebrow">THE WALKTHROUGH / 20 SECONDS</div>
<div class="section-heading"><h2 id="walkthrough-heading">From cue<br>to response.</h2><p>同一套程序，从准备、等待触发，到观察与评分。参与者的画面，和操作者的工作台，各自承担清楚的任务。</p></div>
<figure class="screening">
{video}
<figcaption><span id="walkthrough-note">分阶段脚本演示。所有信号与按键均为合成，无人体记录。</span><span class="downloads"><a href="walkthrough.gif">GIF ↗</a>{'<a href="walkthrough.mp4">MP4 ↗</a>' if has_mp4 else ''}<a href="hero.png">总览 ↗</a></span></figcaption></figure></section>
<section aria-labelledby="screens-heading"><div class="eyebrow">THE SCREENS / SAME RENDERER</div>
<div class="section-heading"><h2 id="screens-heading">Closer.</h2><p>完整尺寸的实际程序画面。测量阶段保持中性背景，只呈现协议需要的内容。</p></div>
{gallery}</section></main>
<footer><div class="provenance"><p>合成输入 · 模拟按键 · 无硬件连接。界面演示不等于显示、按键、生理或磁共振时序验证。20 秒，名义 8 fps；GIF 经 10 ms 时间量化，保留总时长。全部画面来自本项目共享渲染器与实际呈现状态机。</p><a href="provenance.synthetic.json">查看导出来源与文件哈希 ↗</a></div></footer>
</body></html>'''
    (out / 'index.preview.html').write_bytes(document.encode('utf-8'))


def export(out, ffmpeg=None):
    from experiments.interoception import presentation, ui

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    source_paths = dict(renderer=ui.__file__, presenter=presentation.__file__, exporter=__file__)
    source_hashes = {name: sha256(path) for name, path in source_paths.items()}
    views, registry_path = staged_views()
    chosen = {}
    for phase in ('instruction', 'task', 'synchrony'):
        candidates = [view for view in views if view['phase'] == phase]
        chosen[phase] = next((view for view in candidates if view.get('stimulus', {}).get('active')),
                             candidates[len(candidates) // 2])
    for phase, filename in [('instruction', 'participant-instruction.png'),
                            ('task', 'participant-task.png'),
                            ('synchrony', 'participant-rating.png')]:
        ui.participant_card(chosen[phase]).save(out / filename, optimize=True)
    ui.operator_card(family=FAMILY, view=chosen['task'], status='running',
                     psychopy_available=None, output_label='合成演示 · 无人体记录')[0].save(out / 'operator.png', optimize=True)
    ui.showcase(chosen['task'], family=FAMILY).save(out / 'hero.png', optimize=True)
    frames = [ui.showcase(view, family=FAMILY, size=FRAME_SIZE) for view in views]
    gif_report = save_gif(frames, out / 'walkthrough.gif')
    mp4_report = save_mp4(frames, out / 'walkthrough.mp4', ffmpeg) if ffmpeg else None
    write_gallery(out, has_mp4=mp4_report is not None)
    names = ['hero.png', 'participant-instruction.png', 'participant-task.png',
             'participant-rating.png', 'operator.png', 'walkthrough.gif', 'index.preview.html']
    if mp4_report:
        names.append('walkthrough.mp4')
    if source_hashes != {name: sha256(path) for name, path in source_paths.items()}:
        raise RuntimeError('Presentation sources changed during export; rerun after edits finish')
    provenance = dict(
        schema_version='interoception-ui-demo-v1', is_synthetic=True, participants=0,
        staged_demonstration=True, scripted_keys=True, hardware_connected=False,
        physical_timing_validated=False, actual_human_recording=False,
        renderer='experiments.interoception.ui',
        state_machine='experiments.interoception.presentation.TaskPresentation',
        renderer_sha256=source_hashes['renderer'], presenter_sha256=source_hashes['presenter'],
        exporter_sha256=source_hashes['exporter'], registry_sha256=sha256(registry_path),
        pillow_version=pillow_version, seed=0, family=FAMILY,
        font_note='Shared renderer uses installed system fonts; no font files redistributed.',
        fps=FPS, source_frame_count=len(frames), duration_s=DURATION_S,
        frame_size=list(FRAME_SIZE), timings=TIMINGS,
        sampling_note='8 fps documentation sampling may omit brief visual pulses; not a beat-level timing replay.',
        scripted_actions=[dict(time_s=t, action=a, synthetic=True) for t, a in SCRIPTED_ACTIONS.items()],
        observed_phases=list(dict.fromkeys(view['phase'] for view in views)),
        gif=gif_report, mp4=mp4_report,
        files={name: dict(sha256=sha256(out / name), bytes=(out / name).stat().st_size) for name in names})
    (out / 'provenance.synthetic.json').write_bytes((json.dumps(provenance, ensure_ascii=False,
                                                             indent=2, allow_nan=False) + '\n').encode('utf-8'))
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/assets/program')
    parser.add_argument('--ffmpeg', type=Path, help='Optional local FFmpeg executable for H.264 MP4')
    args = parser.parse_args()
    report = export(args.out, args.ffmpeg)
    print(json.dumps(dict(output=str(args.out), frames=report['source_frame_count'],
                          duration_s=report['duration_s'], gif_bytes=report['gif']['bytes'],
                          mp4=report['mp4'] is not None), ensure_ascii=False))
