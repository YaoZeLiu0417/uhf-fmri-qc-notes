"""Small, device-free contracts for the proposed task; no online detector."""
from dataclasses import dataclass
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import random

CELLS = frozenset(product(('heartbeat', 'external'), ('current', 'replay')))
ROOT = Path(__file__).resolve().parents[2]


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite numeric value')
    return float(value)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def simulation_config(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    if cfg.get('schema_version') != 'interoception-interface-v0.1' or cfg.get('mode') != 'simulation' or cfg.get('is_synthetic') is not True:
        raise ValueError('Only an explicitly synthetic simulation configuration is supported')
    if not cfg.get('delay_seconds') or any(finite(v) <= 0 for v in cfg['delay_seconds'].values()):
        raise ValueError('Positive toy delays required')
    for key in ('cue_s', 'observe_s', 'rating_s', 'confidence_s', 'minimum_lead_s'):
        if finite(cfg[key]) <= 0:
            raise ValueError('Positive duration required')
    if not cfg.get('iti_choices_s') or any(finite(v) < 0 for v in cfg['iti_choices_s']):
        raise ValueError('Invalid ITI')
    for key in ('clock_id', 'mapping_id', 'readout_id', 'objective_id'):
        if not isinstance(cfg.get(key), str) or not cfg[key]:
            raise ValueError('An explicit identifier is required')
    return cfg


def private_output(path):
    out = Path(path).resolve()
    if out == ROOT or out.is_relative_to(ROOT):
        raise ValueError('Session outputs must remain outside the public repository')
    if out.exists():
        raise FileExistsError('Choose a new output directory')
    return out


def packet(packet_id, delay_id, seed, role='development'):
    if role not in ('development', 'test') or not packet_id or not delay_id:
        raise ValueError('Invalid packet metadata')
    cells = sorted(CELLS)
    random.Random(seed).shuffle(cells)
    return [dict(packet_id=packet_id, trial_id=f'{packet_id}_{i+1}', delay_id=delay_id,
                 attention=a, linkage=l, role=role) for i, (a, l) in enumerate(cells)]


class CueScheduler:
    """Validate a current-pulse message and plan a cue, without issuing output."""
    def __init__(self, clock_id, mapping_id, minimum_lead_s):
        self.clock_id, self.mapping_id = clock_id, mapping_id
        self.lead = finite(minimum_lead_s)
        if self.lead < 0:
            raise ValueError('Negative scheduling lead')
        self.seen = set()

    def plan_current(self, event, delay_s, now_s):
        now, delay = finite(now_s), finite(delay_s)
        t, available = finite(event['event_time_s']), finite(event['available_time_s'])
        if delay <= 0 or available < t or available > now:
            raise ValueError('Invalid event availability or delay')
        if event['clock_id'] != self.clock_id or event['mapping_id'] != self.mapping_id:
            raise ValueError('Clock mapping mismatch')
        if not isinstance(event.get('is_synthetic'), bool):
            raise ValueError('Explicit synthetic/real provenance required')
        key = event['event_id']
        if not isinstance(key, str) or not key or key in self.seen:
            raise ValueError('Empty or duplicate pulse event ID')
        if event.get('quality') not in ('good', 'ambiguous', 'missing'):
            raise ValueError('Unknown quality state')
        self.seen.add(key)
        due = t + delay
        reason = 'bad_quality' if event['quality'] != 'good' else 'missed_deadline' if now + self.lead > due else None
        return dict(reference_kind='current_pulse', reference_event_id=key,
                    due_time_s=due, status='skipped' if reason else 'scheduled', reason=reason)


def plan_replay(offsets, onset_s, delay_s, replay_id, stop_s):
    onset, delay, stop = finite(onset_s), finite(delay_s), finite(stop_s)
    times = [finite(v) for v in offsets]
    if not replay_id or delay <= 0 or stop <= onset or any(v < 0 for v in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Invalid preloaded replay schedule')
    return [dict(reference_kind='replay_schedule', replay_id=replay_id,
                 replay_event_index=i, due_time_s=onset+t+delay, status='scheduled', reason=None)
            for i, t in enumerate(times) if onset+t+delay < stop]


def build_selection_request(observations, allowed_delay_ids, readout_id, objective_id, now_s):
    now = finite(now_s)
    allowed = tuple(allowed_delay_ids)
    if not allowed or not all(isinstance(x, str) and x for x in allowed) or len(set(allowed)) != len(allowed) or not observations or not readout_id or not objective_id:
        raise ValueError('Unique allowed delays and complete development observations required')
    flags = {row.get('is_synthetic') for row in observations}
    if len(flags) != 1 or not all(isinstance(row.get('is_synthetic'), bool) for row in observations):
        raise ValueError('Synthetic and real observations cannot be mixed')
    groups, seen = {}, set()
    for row in observations:
        if not all(isinstance(row.get(k), str) and row[k] for k in ('trial_id', 'packet_id')):
            raise ValueError('Explicit trial and packet identifiers required')
        if row['role'] != 'development' or row['valid'] is not True:
            raise ValueError('Only valid development observations can update selection')
        if row['readout_id'] != readout_id or row['delay_id'] not in allowed:
            raise ValueError('Readout version or delay mismatch')
        if finite(row['available_time_s']) > now:
            raise ValueError('Readout is not available yet')
        finite(row['value'])
        if row['trial_id'] in seen:
            raise ValueError('Duplicate trial')
        seen.add(row['trial_id'])
        groups.setdefault(row['packet_id'], []).append(row)
    estimates = []
    for pid, rows in groups.items():
        if len(rows) != 4 or {(r['attention'], r['linkage']) for r in rows} != CELLS or len({r['delay_id'] for r in rows}) != 1:
            raise ValueError('Selection requires one complete four-condition packet per delay')
        values = {(r['attention'], r['linkage']): r['value'] for r in rows}
        h = values['heartbeat', 'current'] - values['heartbeat', 'replay']
        e = values['external', 'current'] - values['external', 'replay']
        estimates.append(dict(packet_id=pid, delay_id=rows[0]['delay_id'], contingency_effect=(h+e)/2, attention_dependence=h-e))
    return dict(schema_version='interoception-selector-v0.1', phase='development',
                is_synthetic=observations[0]['is_synthetic'],
                readout_id=readout_id, objective_id=objective_id, allowed_delay_ids=list(allowed),
                decision_time_s=now, estimates=estimates)


def choose_delay(request, external_proposal=None):
    if request['phase'] != 'development':
        raise ValueError('Selection cannot update from held-out data')
    allowed = request['allowed_delay_ids']
    if external_proposal is not None:
        if external_proposal not in allowed:
            raise ValueError('External selector proposed an inadmissible delay')
        return dict(delay_id=external_proposal, policy='external_proposal_unvalidated')
    counts = {d: sum(e['delay_id'] == d for e in request['estimates']) for d in allowed}
    return dict(delay_id=min(allowed, key=lambda d: counts[d]), policy='balanced_fallback_only')


@dataclass(frozen=True)
class FrozenSchedule:
    delay_ids: tuple
    readout_id: str
    objective_id: str
    sha256: str


def freeze_schedule(delay_ids, readout_id, objective_id):
    delays = tuple(delay_ids)
    if not delays or not all(isinstance(x, str) and x for x in delays) or not readout_id or not objective_id:
        raise ValueError('Explicit test schedule and definitions required')
    content = dict(delay_ids=delays, readout_id=readout_id, objective_id=objective_id)
    return FrozenSchedule(delays, readout_id, objective_id, fingerprint(content))
