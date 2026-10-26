"""Exercise the message boundaries using toy timestamps, not a real-time task."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
from .contracts import (CueScheduler, build_selection_request, choose_delay,
                        fingerprint, freeze_schedule, packet, plan_replay,
                        private_output, simulation_config)


def run(config_path, output):
    cfg = simulation_config(config_path)
    out = private_output(output)
    rng = random.Random(cfg['seed'])
    events, observations = [], []
    time = 0.0
    delays = list(cfg['delay_seconds'])
    next_delay = delays[0]

    def log(kind, **fields):
        events.append(dict(fields, schema_version='interoception-log-v0.1', is_synthetic=True,
                           clock_id=cfg['clock_id'], kind=kind))

    def run_packet(pid, delay_id, role):
        nonlocal time
        for trial in packet(pid, delay_id, rng.randrange(2**31), role):
            start = time + cfg['cue_s']
            stop = start + cfg['observe_s']
            log('trial', **trial, onset_s=time, observe_onset_s=start, observe_stop_s=stop)
            offsets = [0.5+i*0.83 for i in range(int(cfg['observe_s']/0.83))]
            if trial['linkage'] == 'current':
                scheduler = CueScheduler(cfg['clock_id'], cfg['mapping_id'], cfg['minimum_lead_s'])
                plans = []
                for i, t in enumerate(offsets):
                    ev = dict(event_id=f"{trial['trial_id']}_pulse_{i}", event_time_s=start+t,
                              available_time_s=start+t+.04, clock_id=cfg['clock_id'],
                              mapping_id=cfg['mapping_id'], quality='good', is_synthetic=True)
                    plan = scheduler.plan_current(ev, cfg['delay_seconds'][delay_id], ev['available_time_s'])
                    log('pulse_event', **ev)
                    if plan['due_time_s'] < stop:
                        plans.append(plan)
            else:
                plans = plan_replay([v+.11 for v in offsets], start, cfg['delay_seconds'][delay_id], 'synthetic_preloaded_episode', stop)
            for plan in plans:
                log('cue_plan', trial_id=trial['trial_id'], **plan)
                if plan['status'] == 'scheduled':
                    log('cue_receipt', trial_id=trial['trial_id'], requested_time_s=plan['due_time_s'],
                        mock_flip_time_s=plan['due_time_s']+.008, measured_output_time_s=None)
            time = stop+cfg['rating_s']+cfg['confidence_s']
            value = rng.randrange(101)
            row = dict(**trial, value=value, readout_id=cfg['readout_id'], available_time_s=time,
                       valid=True, is_synthetic=True)
            observations.append(row)
            log('mock_report', **row, confidence=rng.randrange(1, 5))
            log('mri_readout_unavailable', trial_id=trial['trial_id'], value=None, valid=False,
                reason='No real-time MRI adapter is connected')
            time += rng.choice(cfg['iti_choices_s'])

    for index in range(len(delays)):
        run_packet(f'synthetic_dev_{index+1}', next_delay, 'development')
        request = build_selection_request(observations, delays, cfg['readout_id'], cfg['objective_id'], time)
        decision = choose_delay(request)
        log('selector_request', request=request)
        log('selector_decision', **decision, simulated_time_s=time)
        next_delay = decision['delay_id']
    frozen = freeze_schedule(delays, cfg['readout_id'], cfg['objective_id'])
    log('freeze', **asdict(frozen), simulated_time_s=time)
    for index, delay_id in enumerate(frozen.delay_ids):
        run_packet(f'synthetic_test_{index+1}', delay_id, 'test')
    summary = dict(is_synthetic=True, mode='simulation', participants=0,
                   trial_count=len(observations), test_trials=sum(r['role']=='test' for r in observations),
                   selector='balanced_fallback_only', bayesian_optimizer_implemented=False,
                   live_hardware_connected=False, real_time_validated=False,
                   frozen_plan_sha256=frozen.sha256, config_sha256=fingerprint(cfg),
                   mock_elapsed_seconds=time, event_count=len(events))
    out.mkdir(parents=True)
    with (out/'events.synthetic.jsonl').open('w', encoding='utf-8') as stream:
        for event in events:
            stream.write(json.dumps(event, allow_nan=False)+'\n')
    (out/'summary.synthetic.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('simulation_config.json'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.out), indent=2))
