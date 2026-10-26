"""Compatibility entrypoint for the source-blind four-condition UI demo.

The former double-pulse visual reference is removed from participant views.
Synthetic toy_schedule remains solely for the older contract examples.
"""
import argparse
from pathlib import Path


def toy_schedule(duration, delay, linkage):
    """Precomputed synthetic times for presentation review, never online PPG."""
    if duration <= 0 or delay <= 0 or linkage not in ('current', 'replay'):
        raise ValueError('Invalid simulation schedule')
    pulse = [.5+i*.83 for i in range(int(duration/.83)) if .5+i*.83 < duration]
    replay = [.61+i*.89 for i in range(int(duration/.89))]
    cues = [t+delay for t in (pulse if linkage=='current' else replay) if t+delay < duration]
    return pulse, cues


def run(args):
    if not args.simulate:
        raise ValueError('This prototype requires --simulate and cannot run live acquisition')
    if getattr(args,'config',None) is not None:
        raise ValueError('Use the v0.3 presenter configuration; legacy --config is no longer a GUI protocol')
    from .run_presentation import run as present, parser
    argv=['--simulate','--probe-four','--out',str(args.out)]
    for flag in ('quick','fullscreen'):
        if getattr(args,flag,False):argv.append('--'+flag)
    return present(parser().parse_args(argv))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate',action='store_true');p.add_argument('--quick',action='store_true')
    p.add_argument('--fullscreen',action='store_true');p.add_argument('--config',type=Path)
    p.add_argument('--out',type=Path,required=True)
    raise SystemExit(run(p.parse_args()))
