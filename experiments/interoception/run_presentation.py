"""PsychoPy task-library presenter. All CLI runs are synthetic demonstrations.

Example: python -m experiments.interoception.run_presentation --simulate
         --family body_feedback_synchrony --quick --autoplay --out /private/new_run
The reusable present_block function accepts the existing on-flip bridge.
"""
import argparse
import copy
import json
from pathlib import Path
import queue
import sys
from .contracts import fingerprint, packet, private_output
from .psychopy_bridge import NamedTaskClock, PsychoPyBlockBridge
from .presentation import TaskPresentation
from .ui import FAMILIES, FIELD, participant_card


def _static_key(view):
    # Dynamic task cues are native PsychoPy stimuli, not textures per frame.
    return (view['phase'],view.get('instruction'),json.dumps(view.get('rating'),sort_keys=True))


def _texture(image):
    """Use PsychoPy's PIL path, preserving RGB levels and top-left orientation.

    Raw RGB NumPy textures have different upload/orientation semantics in
    PsychoPy 2025.1.1. A PIL RGB image follows its documented image-file path.
    """
    return image.convert('RGB')


def load_button_mapping(path):
    """Map recorded device key names to two semantic responses, never a trigger."""
    cfg=json.loads(Path(path).read_text(encoding='utf-8'))
    if cfg.get('schema_version')!='interoception-two-button-v1':raise ValueError('Two-button mapping version required')
    groups=[cfg.get(k) for k in ('button_1','button_2','operator_abort','simulated_trigger')]
    if any(not isinstance(g,list) or not g or any(not isinstance(k,str) or not k for k in g) for g in groups):
        raise ValueError('Explicit response, operator and trigger key groups required')
    keys=[key for group in groups for key in group]
    if len(set(keys))!=len(keys):raise ValueError('Participant keys must be separate from operator and trigger keys')
    aliases={key:action for group,action in zip(groups,('1','2','escape','trigger')) for key in group}
    return cfg,aliases


def present_block(win, kb, native_clock, flow, bridge, command, *, event_sink,
                  autoplay=False, captures=None, status_sink=None, key_aliases=None):
    """Present one block and dispatch receipts outside flip callbacks.

    A caller integrating NeuroadaptiveSession must pass the *outstanding*
    command and the same calibrated task clock. This function does not invent
    ROI values or run an optimizer. CLI demonstrations use manual demo commands.
    """
    if (flow.condition_id!=command.get('condition_id') or flow.clock_id!=bridge.clock_id
            or flow.is_synthetic is not bridge.is_synthetic):
        raise ValueError('Presented task, clock and provenance must match the block command')
    from psychopy import visual
    from PIL import Image, ImageDraw
    from .ui import _abstract_scene
    named=native_clock if isinstance(native_clock,NamedTaskClock) else NamedTaskClock(bridge.clock_id,native_clock)
    receipts=queue.SimpleQueue()
    clock=native_clock
    key_aliases=key_aliases or {'1':'1','2':'2','num_1':'1','num_2':'2','escape':'escape','5':'trigger'}
    # Preload the timing-critical static field and procedural demo materials.
    blank=participant_card(dict(phase='task',is_synthetic=flow.is_synthetic),dynamic=False)
    field=visual.ImageStim(win,image=_texture(blank),size=(1280,800),units='pix',autoLog=False)
    fixation=visual.ShapeStim(win,vertices=((-10,0),(10,0),(0,0),(0,-10),(0,10)),
        closeShape=False,lineWidth=2,lineColor='white',units='pix',autoLog=False)
    cue=visual.Circle(win,radius=26,fillColor='white',lineColor='white',units='pix',autoLog=False)
    scenes={}
    # The demo model uses abstract identifiers, never unlicensed photographs.
    for category in ('city','mountain'):
        for i in range(8):
            token=f'demo_{category}_{i}'
            image=Image.new('RGB',(320,240),FIELD)
            _abstract_scene(ImageDraw.Draw(image),{'category':category},160,120)
            scenes[token]=visual.ImageStim(win,image=_texture(image),size=(320,240),units='pix',autoLog=False)
    # Warm up draw calls before the explicit trigger wait. No session events yet.
    field.draw();fixation.draw()
    card=None;card_key=None;last_phase=None;auto_done=set();started=False;ended=False
    frames=0;captured=set();flow.start(clock.getTime())

    def receipt(kind,**fields):
        receipts.put(dict(kind=kind,task_time_s=clock.getTime(),clock_id=bridge.clock_id,
            timestamp_basis='software_flip_callback',is_synthetic=flow.is_synthetic,
            measured_output_time_s=None,physical_trigger_time_s=None,**fields))

    while True:
        now=clock.getTime()
        phase_at_poll=flow.phase
        for key in kb.getKeys(keyList=list(key_aliases),waitRelease=False,clear=True):
            action=key_aliases[key.name]
            event_sink(dict(kind='keyboard_event',key=key.name,rt_s=key.rt,
                task_time_s=now,clock_id=bridge.clock_id,is_synthetic=flow.is_synthetic,
                key_timestamp_basis='keyboard_clock_reset_on_phase_flip'))
            # A response collected on the old page cannot confirm a new page
            # that has not yet been displayed. Escape always remains active.
            if flow.phase==phase_at_poll or action=='escape':flow.advance(now,action=action)
        flow.advance(now)
        view=flow.view(now);phase=view['phase']
        if autoplay:
            elapsed=view['phase_elapsed_s'];key=(phase,flow.condition_id)
            action=None
            if phase=='instruction' and elapsed>=max(.7,flow.timings['instruction_s']) and key not in auto_done:action='1'
            elif phase=='trigger_wait' and elapsed>=.7 and key not in auto_done:action='trigger'
            elif phase in ('synchrony','confidence') and elapsed>=.7 and key not in auto_done:action='2'
            if action:
                auto_done.add(key);flow.advance(now,action=action);view=flow.view(now);phase=view['phase']
                event_sink(dict(kind='synthetic_autoplay_action',action=action,task_time_s=now,is_synthetic=True))
        if phase!=last_phase:
            if phase=='task' and not started:
                bridge.queue_start_on_flip(win,command,named,view['duration_s'],receipts.put)
                started=True
            elif started and not ended and last_phase=='task':
                bridge.queue_end_on_flip(win,command['block_id'],named,receipts.put);ended=True
            win.callOnFlip(kb.clock.reset)
            win.callOnFlip(kb.clearEvents)
            win.callOnFlip(receipt,'phase_flip',phase=phase)
            if status_sink:status_sink(view)
        if phase=='task':
            field.draw();stim=view['stimulus'];kind=stim['kind']
            if kind in ('feedback_ring','visual_rhythm') and stim.get('active'):
                level=round(255*float(stim.get('intensity',1.)))
                cue.fillColor=f'#{level:02X}{level:02X}{level:02X}'
                cue.lineColor=cue.fillColor;cue.draw()
            elif kind=='gradcpt':
                first,second=stim.get('from_image'),stim.get('to_image')
                if first not in scenes or second not in scenes:
                    raise ValueError('CLI demonstration only accepts preloaded abstract materials')
                scenes[first].opacity=1.;scenes[first].draw()
                scenes[second].opacity=stim['mix'];scenes[second].draw()
            else:fixation.draw()
        else:
            key=_static_key(view)
            if key!=card_key:
                card=visual.ImageStim(win,image=_texture(participant_card(view)),size=(1280,800),units='pix',autoLog=False)
                card_key=key
            card.draw()
        if captures is not None and phase not in captured:
            # Captures intentionally interrupt performance; not a timing run.
            win.getMovieFrame(buffer='back')
            captures[phase]=win.movieFrames.pop().copy();captured.add(phase)
        win.flip();frames+=1
        while not receipts.empty():event_sink(receipts.get_nowait())
        for row in flow.drain_events():event_sink(row)
        if phase in ('complete','aborted'):
            return dict(status='aborted' if phase=='aborted' else 'completed',frames=frames,view=view)
        last_phase=phase


def run(args):
    if not args.simulate:raise ValueError('This CLI currently requires --simulate; live devices are not connected')
    from psychopy import visual,core
    from psychopy.hardware import keyboard
    import psychopy
    mapping,key_aliases=load_button_mapping(args.button_map)
    out=private_output(args.out);out.mkdir(parents=True)
    spec=[dict(condition_id=f'{args.family}_p1',family=args.family,parameter_values={})]
    if args.probe_four:
        spec=[dict(condition_id=t['trial_id'],family='body_feedback_synchrony',
                   parameter_values=dict(attention=t['attention'],linkage=t['linkage']))
              for t in packet('body_feedback_demo','toy_delay',args.seed)]
    space=dict(clock_id='presentation_demo_clock',is_synthetic=True,
        conditions=[{'condition_id':r['condition_id']} for r in spec])
    space['definition_sha256']=fingerprint(space)
    definition=fingerprint(dict(space=space,timings='quick' if args.quick else 'demo',seed=args.seed))
    bridge=PsychoPyBlockBridge(space,'presentation_demo',definition)
    durations=dict(instruction_s=1.5,task_s=4. if args.quick else 12.,
        synchrony_s=2. if args.quick else 5.,confidence_s=2. if args.quick else 4.,
        fixation_s=1. if args.quick else 3.)
    clock=core.MonotonicClock();named_clock=NamedTaskClock(space['clock_id'],clock)
    kb=keyboard.Keyboard();win=None;capture_frames={};rows=[]
    status='aborted';error=None

    def emit(row):rows.append(copy.deepcopy(row))

    def update(view):
        # Operator files contain only a public-safe synthetic view, no identifiers.
        path=out/'operator_status.private.json';tmp=out/'operator_status.tmp'
        tmp.write_text(json.dumps(dict(is_synthetic=True,view=view),ensure_ascii=False,allow_nan=False),encoding='utf-8')
        tmp.replace(path)

    try:
        win=visual.Window(size=(1280,800),fullscr=args.fullscreen,screen=args.screen,
            units='pix',color=FIELD,colorSpace='hex',checkTiming=False,autoLog=False,
            title='Interoception · SYNTHETIC DEMO',allowGUI=not args.fullscreen)
        win.recordFrameIntervals=True
        emit(dict(kind='session_start',version='0.3',is_synthetic=True,
            psychopy_version=psychopy.__version__,keyboard_backend=str(getattr(kb,'backend','unknown')),
            mode='synthetic_autoplay' if args.autoplay else 'synthetic_manual',
            clock_id=space['clock_id'],definition_hash=definition,live_hardware_connected=False,
            graphics_capture_enabled=args.capture,physical_timing_validated=False,
            response_contract='two_button_binary_v1',button_mapping=mapping,
            button_mapping_sha256=fingerprint(mapping)))
        for index,row in enumerate(spec):
            flow=TaskPresentation(row,mode='demo',clock_id=space['clock_id'],timings=durations,seed=args.seed+index)
            cmd=dict(kind='next_block_recommendation',run_id='presentation_demo',block_id=f'demo_block_{index+1}',
                condition_id=row['condition_id'],role='development',decision_time_s=clock.getTime(),
                clock_id=space['clock_id'],definition_hash=definition,is_synthetic=True,
                selection_basis='manual_demo_selection_not_an_optimizer_decision')
            result=present_block(win,kb,named_clock,flow,bridge,cmd,event_sink=emit,
                autoplay=args.autoplay,captures=capture_frames if args.capture else None,status_sink=update,key_aliases=key_aliases)
            if result['status']=='aborted':break
        else:status='completed'
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc));raise
    finally:
        intervals=list(win.frameIntervals) if win else []
        if win:win.close()
        for name,image in capture_frames.items():image.save(out/(name+'.actual-psychopy.synthetic.png'))
        with (out/'presentation.synthetic.jsonl').open('x',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        summary=dict(version='0.3',status=status,error=error,is_synthetic=True,
            psychopy_version=psychopy.__version__,participants=0,live_devices=0,
            autoplay=args.autoplay,capture_interrupted_performance=args.capture,
            block_count=len([r for r in rows if r.get('kind')=='block_started']),
            ended_block_count=len([r for r in rows if r.get('kind')=='block_ended']),
            frames_recorded=len(intervals),frame_intervals_s=intervals,
            physical_display_timing_validated=False,response_device_validated=False,
            response_contract='two_button_binary_v1',participant_buttons=['1','2'],button_mapping_sha256=fingerprint(mapping))
        (out/'presentation_summary.private.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    return 0 if status=='completed' else 130


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate',action='store_true')
    p.add_argument('--family',choices=tuple(FAMILIES),default='heartbeat_attention')
    p.add_argument('--probe-four',action='store_true',help='Four source-blind body-feedback demo cells')
    p.add_argument('--quick',action='store_true',help='Short interface review; not final human timings')
    p.add_argument('--autoplay',action='store_true',help='Synthetic responses and simulated trigger')
    p.add_argument('--capture',action='store_true',help='Capture actual back-buffer images; affects frame performance')
    p.add_argument('--fullscreen',action='store_true');p.add_argument('--screen',type=int,default=0)
    p.add_argument('--seed',type=int,default=20261026);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--button-map',type=Path,default=Path(__file__).with_name('button_mapping.template.json'))
    return p


if __name__=='__main__':sys.exit(run(parser().parse_args()))
