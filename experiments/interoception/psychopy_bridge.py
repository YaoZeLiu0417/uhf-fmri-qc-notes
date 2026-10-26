"""Small on-flip hook between session recommendations and a PsychoPy window.

No PsychoPy import is needed to test the contract. In a PsychoPy programme:

    events = queue.SimpleQueue()
    clock = NamedTaskClock(space['clock_id'], core.MonotonicClock())
    bridge = PsychoPyBlockBridge(space, session.run_id, session.definition_hash)
    bridge.queue_start_on_flip(win, command, clock, duration_s, events.put)
    # Draw the selected task, then win.flip(). Outside the flip callback:
    session.dispatch(events.get_nowait())
    # At the actual end, draw fixation, then:
    bridge.queue_end_on_flip(win, command['block_id'], clock, events.put)
    win.flip()
    session.dispatch(events.get_nowait())

The event sink must only enqueue the event. Drain that queue serially in the
controller; do not run GLMs, optimizers, disk flushes or network requests in
the flip callback. The timestamp is a software flip-callback time, not an
independent physical display measurement or scanner TTL. A matching clock ID
is a contract label, not evidence that hardware clocks have been calibrated.
"""
from copy import deepcopy
import math
import numbers


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number of seconds')
    return float(value)


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Explicit {name} required')
    return value


class NamedTaskClock:
    """Bind an explicitly identified task clock to a native getTime() clock."""
    def __init__(self, clock_id, native_clock):
        self.clock_id = _identifier(clock_id, 'clock ID')
        if not callable(getattr(native_clock, 'getTime', None)):
            raise ValueError('A native getTime() clock is required')
        self._native_clock = native_clock

    def getTime(self):
        return self._native_clock.getTime()


class PsychoPyBlockBridge:
    """One queued block at a time, with registry/run/phase/clock validation."""
    def __init__(self, space, run_id, definition_hash, role='development'):
        if not isinstance(space, dict) or not isinstance(space.get('conditions'), list):
            raise ValueError('Explicit condition registry required')
        ids = [c.get('condition_id') for c in space['conditions'] if isinstance(c, dict)]
        if len(ids) != len(space['conditions']) or not ids or not all(isinstance(c, str) and c for c in ids) or len(set(ids)) != len(ids):
            raise ValueError('Unique registered condition IDs required')
        if role != 'development':
            raise ValueError('Test phase requires a verified freeze receipt')
        if not isinstance(space.get('is_synthetic'), bool):
            raise ValueError('Explicit synthetic/real registry provenance required')
        self.condition_ids = frozenset(ids)
        self.clock_id = _identifier(space.get('clock_id'), 'registry clock ID')
        self.registry_hash = _identifier(space.get('definition_sha256'), 'registry definition hash')
        self.run_id = _identifier(run_id, 'run ID')
        self.definition_hash = _identifier(definition_hash, 'session definition hash')
        self.is_synthetic = space['is_synthetic']
        self.role = role
        self._not_before = float('-inf')
        self._clock = None
        self._last_clock = float('-inf')
        self._last_decision = float('-inf')
        self._last_onset = float('-inf')
        self._previous_end = float('-inf')
        self._seen = set()
        self._end_attempted = set()
        self._ended = set()
        self._active_block = None
        self._pending = None

    def set_phase(self, role, *, not_before_s, freeze_receipt):
        """Enter test after the controller returns its actual freeze receipt."""
        if role != 'test' or self.role != 'development' or self._pending is not None or self._active_block is not None:
            raise ValueError('Only an idle development-to-test transition is allowed')
        boundary = _time(not_before_s, 'test phase boundary')
        if not isinstance(freeze_receipt, dict) or freeze_receipt.get('status') != 'frozen':
            raise ValueError('A controller freeze receipt is required')
        snapshot = freeze_receipt.get('snapshot', {})
        if not isinstance(snapshot, dict):
            raise ValueError('A structured frozen snapshot is required')
        optimizer = snapshot.get('optimizer', {})
        if not isinstance(optimizer, dict):
            raise ValueError('A structured optimizer freeze receipt is required')
        if snapshot.get('definition_hash') != self.definition_hash or optimizer.get('run_id') != self.run_id or optimizer.get('frozen') is not True:
            raise ValueError('Freeze receipt does not match this run and definition')
        freeze_time = _time(snapshot.get('freeze_time_s'), 'controller freeze time')
        if boundary < freeze_time or boundary < self._last_clock or boundary < self._previous_end:
            raise ValueError('Test phase cannot precede the freeze or the completed block')
        self.role, self._not_before = 'test', boundary

    def queue_start_on_flip(self, window, command, task_clock, duration_s, event_sink):
        """Queue one actual-onset event; this function itself emits no event.

        ``duration_s`` is the planned duration. Register this hook immediately
        before the flip displaying the selected task and register an end hook
        on the flip that actually ends it. Failure after a physical flip must abort/reconcile the session,
        not replay the same command. Command dictionaries are copied now so
        subsequent caller edits cannot change the queued event.
        """
        if self._pending is not None:
            raise ValueError('An earlier flip callback is still pending')
        if not callable(getattr(window, 'callOnFlip', None)) or not callable(event_sink):
            raise ValueError('callOnFlip window and nonblocking event sink required')
        if not isinstance(command, dict) or command.get('kind') != 'next_block_recommendation':
            raise ValueError('Expected next_block_recommendation command')
        if command.get('run_id') != self.run_id or command.get('role') != self.role:
            raise ValueError('Command run or phase mismatch')
        if command.get('definition_hash') != self.definition_hash:
            raise ValueError('Command definition hash mismatch')
        condition = command.get('condition_id')
        if not isinstance(condition, str) or condition not in self.condition_ids:
            raise ValueError('Unknown condition in command')
        block_id = _identifier(command.get('block_id'), 'block ID')
        if block_id in self._seen:
            raise ValueError('Duplicate or replayed block command')
        if command.get('is_synthetic') is not self.is_synthetic:
            raise ValueError('Command data provenance changed')
        if getattr(task_clock, 'clock_id', None) != self.clock_id or not callable(getattr(task_clock, 'getTime', None)):
            raise ValueError('Task clock identity mismatch')
        if self._clock is not None and task_clock is not self._clock:
            raise ValueError('Changing the task clock object requires a new bridge')
        if 'clock_id' in command and command['clock_id'] != self.clock_id:
            raise ValueError('Command clock identity mismatch')
        now = _time(task_clock.getTime(), 'queue time')
        decision = _time(command.get('decision_time_s'), 'decision time')
        duration = _time(duration_s, 'block duration')
        if duration <= 0 or decision > now or decision <= self._last_decision or decision < self._last_onset:
            raise ValueError('Invalid duration or stale/future command time')
        if now < self._last_clock or decision < self._not_before or now < self._not_before:
            raise ValueError('Clock moved backwards or command predates this phase')
        if self._active_block is not None:
            raise ValueError('The previous block has no actual end event')
        copied = deepcopy(command)
        state = {'executed': False}

        def on_flip():
            if state['executed']:
                raise ValueError('Flip callback cannot execute twice')
            state['executed'] = True
            try:
                onset = _time(task_clock.getTime(), 'actual flip callback time')
                if onset < now or onset < self._last_clock or onset < decision or onset < self._not_before or onset < self._previous_end:
                    raise ValueError('Clock moved backwards or actual blocks overlap')
                self._last_clock, self._last_onset = onset, onset
                self._last_decision = decision
                self._active_block = dict(block_id=block_id, onset_s=onset,
                    planned_duration_s=duration, command=copied)
                event_sink(dict(kind='block_started', command=copied, onset_s=onset,
                    duration_s=duration, planned_duration_s=duration,
                    duration_basis='planned_until_block_ended', run_id=self.run_id, role=self.role,
                    condition_id=condition, definition_hash=self.definition_hash,
                    registry_definition_sha256=self.registry_hash, clock_id=self.clock_id,
                    is_synthetic=self.is_synthetic, onset_basis='software_flip_callback',
                    actual_flip_callback_time_s=onset, physical_trigger_time_s=None,
                    measured_output_time_s=None))
            finally:
                self._pending = None

        self._pending = state
        self._seen.add(block_id)
        try:
            window.callOnFlip(on_flip)
        except Exception:
            self._pending = None
            if not state['executed']:
                self._seen.remove(block_id)
            raise
        self._clock, self._last_clock = task_clock, now
        return dict(status='queued_for_flip', block_id=block_id, condition_id=condition)

    def queue_end_on_flip(self, window, block_id, task_clock, event_sink):
        """Queue a software offset timestamp on the flip ending the active task.

        The planned duration is never substituted for this offset. An unknown,
        repeated or unstarted block cannot be ended. The end sink must enqueue
        the event for serial dispatch, just like the start sink.
        """
        if self._pending is not None:
            raise ValueError('An earlier flip callback is still pending')
        if not callable(getattr(window, 'callOnFlip', None)) or not callable(event_sink):
            raise ValueError('callOnFlip window and nonblocking event sink required')
        block_id = _identifier(block_id, 'block ID')
        if block_id in self._end_attempted or block_id in self._ended:
            raise ValueError('Duplicate or replayed block end')
        block = self._active_block
        if block is None or block['block_id'] != block_id:
            raise ValueError('Cannot end an unknown or unstarted block')
        if task_clock is not self._clock or getattr(task_clock, 'clock_id', None) != self.clock_id:
            raise ValueError('Task clock identity or object mismatch')
        now = _time(task_clock.getTime(), 'end queue time')
        if now < self._last_clock or now < block['onset_s']:
            raise ValueError('Clock moved backwards before block end')
        state = {'executed': False}

        def on_flip():
            if state['executed']:
                raise ValueError('End flip callback cannot execute twice')
            state['executed'] = True
            try:
                offset = _time(task_clock.getTime(), 'actual end flip callback time')
                if offset < now or offset < self._last_clock or offset <= block['onset_s']:
                    raise ValueError('Clock moved backwards or end does not follow start')
                self._last_clock, self._previous_end = offset, offset
                self._active_block = None
                self._ended.add(block_id)
                event_sink(dict(kind='block_ended', block_id=block_id, offset_s=offset,
                    run_id=self.run_id, role=self.role,
                    condition_id=block['command']['condition_id'],
                    planned_duration_s=block['planned_duration_s'],
                    software_duration_s=offset-block['onset_s'],
                    definition_hash=self.definition_hash, registry_definition_sha256=self.registry_hash,
                    clock_id=self.clock_id, is_synthetic=self.is_synthetic,
                    offset_basis='software_flip_callback', actual_flip_callback_time_s=offset,
                    physical_trigger_time_s=None, measured_output_time_s=None))
            finally:
                self._pending = None

        self._pending = state
        self._end_attempted.add(block_id)
        try:
            window.callOnFlip(on_flip)
        except Exception:
            self._pending = None
            if not state['executed']:
                self._end_attempted.remove(block_id)
            raise
        self._last_clock = now
        return dict(status='end_queued_for_flip', block_id=block_id)
