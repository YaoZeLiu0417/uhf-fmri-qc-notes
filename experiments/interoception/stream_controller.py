"""Process causal JSONL ROI/readout messages into block recommendations.

Input '-' reads stdin and flushes one response per received event. This bridge
does not acquire images, present stimuli, or verify site calibration claims.
"""
import argparse
import json
from pathlib import Path
import sys
from .contracts import private_output
from .session import NeuroadaptiveSession
from .taskspace import load_taskspace


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--space',type=Path,required=True);p.add_argument('--input-jsonl',required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--direction',type=int,choices=[-1,1],default=1);p.add_argument('--seed',type=int,default=0)
    p.add_argument('--acquisition',choices=['ei','gp_ucb'],default='ei');p.add_argument('--budget',type=int,default=16)
    args=p.parse_args();space=load_taskspace(args.space);out=private_output(args.out);out.mkdir(parents=True)
    session=NeuroadaptiveSession(space,args.run_id,direction=args.direction,seed=args.seed,budget=args.budget,acquisition=args.acquisition)
    source=sys.stdin if args.input_jsonl=='-' else Path(args.input_jsonl).open(encoding='utf-8')
    with (out/'controller.private.jsonl').open('x',encoding='utf-8') as log:
        try:
            for line in source:
                if not line.strip():continue
                event=None
                try:
                    event=json.loads(line)
                    if not isinstance(event,dict):raise ValueError('JSON event must be an object')
                    response=session.dispatch(event)
                except (KeyError,TypeError,ValueError,AttributeError) as exc:
                    # Invalid inputs never become a new stimulus recommendation.
                    response=dict(status='rejected',reason=str(exc),actuates_hardware=False)
                    if not isinstance(event,dict):event={'unparsed_input':line.rstrip()}
                row=dict(event=event,response=response,is_synthetic=space['is_synthetic'])
                log.write(json.dumps(row,allow_nan=False)+'\n');log.flush()
                print(json.dumps(response,allow_nan=False),flush=True)
        finally:
            if source is not sys.stdin:source.close()


if __name__=='__main__':main()
