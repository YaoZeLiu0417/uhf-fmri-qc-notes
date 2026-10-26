"""Event-driven ROI stream to GLM to GP controller. No scanner/device drivers.

Commands are recommendations to an external presentation adapter. The caller
must record actual flip onsets, QC, clock mapping and independent calibration.
"""
import copy
from .contracts import finite, fingerprint
from .neuroadaptive import NeuroadaptiveOptimizer
from .roi_glm import IncrementalROIGLM


class NeuroadaptiveSession:
    def __init__(self,space,run_id,*,direction=1,seed=0,budget=16,acquisition='ei'):
        if direction not in (1,-1) or isinstance(direction,bool):raise ValueError('Explicit contrast direction required')
        if isinstance(budget,bool) or not isinstance(budget,int) or budget<1:raise ValueError('Positive block budget required')
        if fingerprint({k:v for k,v in space.items() if k!='definition_sha256'})!=space.get('definition_sha256'):
            raise ValueError('Task-space definition changed after loading')
        self.space=copy.deepcopy(space);self.run_id,self.direction,self.budget=run_id,direction,budget
        space=self.space
        self.phase='development';self.pending=None;self.blocks=[];self.test_blocks=[]
        self.freeze_time=None;self.frozen=None
        self.glm=self._new_glm()
        coordinates={r['condition_id']:r['coordinates'] for r in space['conditions']}
        self.optimizer=NeuroadaptiveOptimizer(coordinates,acquisition=acquisition,seed=seed,
            **space['optimizer']).reset(run_id)
        self.definition_hash=fingerprint(dict(space=space['definition_sha256'],direction=direction,
             glm=self.glm.definition_hash,objective='candidate_region_III_minus_IV',acquisition=acquisition))

    def _new_glm(self):
        return IncrementalROIGLM(self.space['clock_id'],units='percent_signal_change',
            roi_definition_id=self.space['roi_definition_id'],**self.space.get('glm',{}))

    def _records(self):return self.blocks if self.phase=='development' else self.test_blocks

    def propose(self,now_s):
        now=finite(now_s)
        if self.pending is not None:return dict(status='awaiting_actual_block_start',command=self.pending)
        records=self._records()
        if records:
            if not records[-1]['ended']:
                return dict(status='waiting_for_actual_block_end',block_id=records[-1]['block_id'])
            current=self.glm.score(records[-1]['block_id'],now)
            if current['status']!='ok':return dict(status='waiting_for_eligible_readout',readout=current)
        if self.phase=='development':
            if len(self.blocks)>=self.budget:return dict(status='ready_to_freeze',block_count=len(self.blocks))
            snapshot=[]
            for block in self.blocks:
                score=self.glm.score(block['block_id'],now)
                if score['status']!='ok':return dict(status='waiting_for_eligible_readout',readout=score)
                # Correlated, unwhitened OLS variances do not override the
                # independently frozen GP noise. Keep them in readout logs.
                snapshot.append(dict(run_id=self.run_id,block_id=block['block_id'],
                    condition_id=block['condition_id'],role='development',
                    value=self.direction*score['beta_difference']))
            self.optimizer.fit(snapshot)
            decision=self.optimizer.suggest()
            cid=decision['condition_id'];reason=decision['reason'];role='development'
        else:
            plan=self.space['fixed_test_plan']
            if len(self.test_blocks)>=len(plan):return dict(status='test_complete')
            cid=plan[len(self.test_blocks)];reason='predefined_independent_test_plan';role='test';decision=None
        self.pending=dict(kind='next_block_recommendation',run_id=self.run_id,
            block_id=f'{self.run_id}_{role}_{len(records)+1:03}',condition_id=cid,role=role,
            reason=reason,decision_time_s=now,definition_hash=self.definition_hash,
            is_synthetic=self.space['is_synthetic'],actuates_hardware=False)
        return dict(status='recommendation',command=self.pending,optimization=decision)

    def begin_block(self,command,onset_s,duration_s):
        if self.pending is None or command!=self.pending:raise ValueError('Block must match the outstanding recommendation')
        onset,duration=finite(onset_s),finite(duration_s)
        if duration<=0 or onset<command['decision_time_s']:raise ValueError('Actual onset must follow its decision')
        records=self._records()
        if records and onset<records[-1]['onset_s']+records[-1]['duration_s']+self.glm.hrf_tail_s:
            raise ValueError('Previous block readout window has not completed')
        self.glm.add_block(command['block_id'],onset,duration,role=command['role'])
        record=dict(command,onset_s=onset,duration_s=duration,planned_duration_s=duration,ended=False)
        records.append(record);self.pending=None
        return dict(status='block_registered',block=record)

    def end_block(self,block_id,offset_s):
        records=self._records();offset=finite(offset_s)
        if not records or records[-1]['block_id']!=block_id or records[-1]['ended']:
            raise ValueError('End must match the current unfinished block')
        self.glm.update_block_offset(block_id,offset)
        records[-1].update(duration_s=offset-records[-1]['onset_s'],actual_offset_s=offset,ended=True)
        return dict(status='actual_block_end_registered',block_id=block_id,offset_s=offset)

    def add_volume(self,*,volume_id,sample_time_s,roi_values,available_time_s,
                   clock_id,roi_definition_id,is_synthetic,valid=True,motion=None):
        if roi_definition_id!=self.space['roi_definition_id'] or is_synthetic is not self.space['is_synthetic']:
            raise ValueError('ROI definition or data provenance changed')
        if self.phase=='test' and finite(sample_time_s)<self.freeze_time:
            raise ValueError('Development samples cannot enter the independent test GLM')
        self.glm.add_volume(volume_id,sample_time_s,roi_values,available_time_s,clock_id,valid,motion)
        return dict(status='volume_received',volume_id=volume_id)

    def readouts(self,now_s):
        return [dict(self.glm.score(b['block_id'],now_s),condition_id=b['condition_id']) for b in self._records()]

    def freeze(self,now_s):
        now=finite(now_s)
        if self.phase!='development' or self.pending is not None:raise ValueError('Cannot freeze an active command or an already frozen session')
        if not self.blocks or not all(b['ended'] for b in self.blocks) or any(r['status']!='ok' for r in self.readouts(now)):
            raise ValueError('Complete development readouts before freeze')
        # Fit the final complete snapshot before taking the immutable boundary.
        self.optimizer.fit([dict(run_id=self.run_id,block_id=r['block_id'],condition_id=r['condition_id'],
             role='development',value=self.direction*r['beta_difference']) for r in self.readouts(now)])
        self.frozen=dict(optimizer=self.optimizer.freeze(),prediction=self.optimizer.posterior(),
             test_plan=list(self.space['fixed_test_plan']),definition_hash=self.definition_hash,
             freeze_time_s=now,development_readouts=self.readouts(now))
        self.development_glm=self.glm
        self.glm=self._new_glm()  # test nuisance estimates never refit the training GLM
        self.phase='test';self.freeze_time=now
        return dict(status='frozen',snapshot_sha256=fingerprint(self.frozen),snapshot=self.frozen)

    def dispatch(self,event):
        kind=event.get('kind')
        if kind=='request_next':return self.propose(event['now_s'])
        if kind=='block_started':return self.begin_block(event['command'],event['onset_s'],event['duration_s'])
        if kind=='block_ended':return self.end_block(event['block_id'],event['offset_s'])
        if kind=='roi_volume':return self.add_volume(**{k:v for k,v in event.items() if k!='kind'})
        if kind=='readouts':return dict(status='readouts',values=self.readouts(event['now_s']))
        if kind=='freeze':return self.freeze(event['now_s'])
        raise ValueError('Unknown event type')
