"""Incrementally refit an ROI-stream GLM, without scanner preprocessing.

Inputs must already be independently extracted, QC-labelled and clock-mapped.
The canonical two-gamma HRF uses response/undershoot shapes 6/16, ratio 6,
and a 32-second kernel, following SPM's default parameterisation:
https://github.com/spm/spm/blob/main/spm_hrf.m
This prototype normalises the sampled kernel to unit integral. It is not a
byte-identical SPM/FSL pipeline, does not whiten temporally correlated noise,
and does not establish physiological or neural specificity of either ROI.
"""
import hashlib
import json
import numbers
import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.stats import gamma


def _finite(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real) or not np.isfinite(value):
        raise ValueError('A finite numeric timestamp or value is required')
    return float(value)


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Explicit {name} required')
    return value


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def block_regressor(sample_times_s, onset_s, duration_s, hrf_dt_s=.1):
    """Sample a boxcar convolved with a unit-integral, truncated double gamma.

    Integrating the sampled HRF then subtracting two shifted integrals avoids
    rounding a fractional actual onset onto a scanner-volume boundary.
    """
    onset, duration, dt = _finite(onset_s), _finite(duration_s), _finite(hrf_dt_s)
    times = np.asarray(sample_times_s, dtype=float)
    if duration <= 0 or not 0 < dt <= .5 or times.ndim != 1 or not np.isfinite(times).all():
        raise ValueError('Finite sample times, positive duration and HRF step <=0.5 s required')
    grid = np.linspace(0., 32., int(np.ceil(32./dt))+1)
    kernel = gamma.pdf(grid, 6.)-gamma.pdf(grid, 16.)/6.
    integral = cumulative_trapezoid(kernel, grid, initial=0.)
    integral /= integral[-1]
    return np.interp(times-onset, grid, integral, left=0., right=1.)-np.interp(
        times-onset-duration, grid, integral, left=0., right=1.)


class IncrementalROIGLM:
    """One regressor per actual block, intercept, drift and optional six motion terms.

    Scores require data through block offset plus the full HRF kernel. The
    default 32-second wait is a conservative prototype rule, not the timing
    used in Lorenz 2018/2021. ``score`` refits all data available at ``now_s``;
    previously returned block estimates can therefore change. Returned OLS
    variance assumes iid residuals and is not a validated live-fMRI error bar.
    """
    def __init__(self, clock_id, units='percent_signal_change', hrf_tail_s=32.,
                 hrf_dt_s=.1, include_motion=False, min_residual_df=4,
                 roi_definition_id='candidate_roi_iii_iv_unvalidated'):
        self.clock_id = _identifier(clock_id, 'mapped clock ID')
        self.units = _identifier(units, 'common ROI units')
        self.hrf_tail_s, self.hrf_dt_s = _finite(hrf_tail_s), _finite(hrf_dt_s)
        if self.hrf_tail_s < 32. or not 0 < self.hrf_dt_s <= .5:
            raise ValueError('Wait through the full 32-second kernel and use HRF step <=0.5 s')
        if not isinstance(include_motion, bool) or isinstance(min_residual_df, bool) or not isinstance(min_residual_df, int) or min_residual_df < 1:
            raise ValueError('Motion flag and positive integer residual degrees of freedom required')
        self.include_motion, self.min_residual_df = include_motion, min_residual_df
        self.blocks, self.volumes = [], []
        self.definition = dict(schema_version='roi-stream-glm-v0.1', clock_id=clock_id,
            roi_order=['III', 'IV'], roi_definition_id=_identifier(roi_definition_id, 'ROI definition ID'),
            units=units, target='beta_III_minus_beta_IV', hrf='gamma6_minus_gamma16_over6_unit_integral_32s',
            hrf_dt_s=self.hrf_dt_s, hrf_tail_wait_s=self.hrf_tail_s,
            design='actual_block_boxcars_intercept_linear_drift', include_six_motion=include_motion,
            min_residual_df=min_residual_df, uncertainty_model='iid_ols_unwhitened')
        self.definition_hash = _hash(self.definition)

    def add_block(self, block_id, onset_s, duration_s, role='development'):
        block_id = _identifier(block_id, 'block ID')
        onset, duration = _finite(onset_s), _finite(duration_s)
        if duration <= 0 or role not in ('development', 'test') or any(b['block_id'] == block_id for b in self.blocks):
            raise ValueError('Unique block ID, positive actual duration and explicit data role required')
        if self.blocks and onset < self.blocks[-1]['onset_s']:
            raise ValueError('Actual block onsets must be registered in chronological order')
        self.blocks.append(dict(block_id=block_id, onset_s=onset, duration_s=duration, role=role))

    def update_block_offset(self, block_id, offset_s):
        """Replace a planned boxcar duration with its recorded actual offset.

        The controller must separately require an actual block-ended event
        before requesting scores. This update does not itself verify a display
        callback, alter the onset, or permit overlap with the next block.
        """
        offset = _finite(offset_s)
        index = next((i for i, b in enumerate(self.blocks) if b['block_id'] == block_id), None)
        if index is None:
            raise ValueError('Unknown block ID')
        block = self.blocks[index]
        if offset <= block['onset_s']:
            raise ValueError('Actual block offset must follow its onset')
        if index+1 < len(self.blocks) and offset > self.blocks[index+1]['onset_s']:
            raise ValueError('Actual block offset overlaps the next registered block')
        self.blocks[index] = dict(block, duration_s=offset-block['onset_s'])
        return dict(self.blocks[index])

    def add_volume(self, volume_id, sample_time_s, roi_values, available_time_s,
                   clock_id, valid=True, motion=None):
        t, available = _finite(sample_time_s), _finite(available_time_s)
        if isinstance(volume_id, (bool, np.bool_)) or not isinstance(volume_id, numbers.Integral) or volume_id < 0:
            raise ValueError('Nonnegative integer volume ID required')
        if clock_id != self.clock_id or available < t or not isinstance(valid, bool):
            raise ValueError('Clock mapping, availability or explicit QC flag is invalid')
        if self.volumes:
            last = self.volumes[-1]
            if volume_id <= last['volume_id'] or t <= last['sample_time_s'] or available < last['available_time_s']:
                raise ValueError('Volume IDs, sample times and arrival times must remain ordered')
        if valid:
            if roi_values is None or len(roi_values) != 2:
                raise ValueError('Two same-unit finite ROI values required for a valid volume')
            roi = tuple(_finite(v) for v in roi_values)
            if self.include_motion and (motion is None or len(motion) != 6):
                raise ValueError('Exactly six fixed motion columns required')
            m = tuple(_finite(v) for v in motion) if self.include_motion else ()
        else:
            roi, m = None, None
        if not self.include_motion and motion is not None:
            raise ValueError('Motion values supplied without enabling six motion regressors')
        self.volumes.append(dict(volume_id=int(volume_id), sample_time_s=t,
            available_time_s=available, roi=roi, motion=m, valid=valid))

    def score(self, block_id, now_s):
        now = _finite(now_s)
        block = next((b for b in self.blocks if b['block_id'] == block_id), None)
        if block is None:
            raise ValueError('Unknown block ID')
        output = dict(block_id=block_id, role=block['role'], beta_difference=None, variance=None,
            block_onset_s=block['onset_s'], block_duration_s=block['duration_s'],
            block_offset_s=block['onset_s']+block['duration_s'],
            definition_hash=self.definition_hash, units=self.units, roi_order=['III', 'IV'],
            uncertainty_model='iid_ols_unwhitened', score_requested_time_s=now,
            availability_basis='caller_supplied_score_time; controller_must_timestamp_actual_completion')
        rows = [v for v in self.volumes if v['available_time_s'] <= now]
        valid = [v for v in rows if v['valid']]
        output.update(n_available_volumes=len(rows), n_valid_volumes=len(valid),
                      n_censored_volumes=len(rows)-len(valid))
        ready_at = block['onset_s']+block['duration_s']+self.hrf_tail_s
        if not valid or valid[-1]['sample_time_s'] < ready_at:
            return dict(output, status='pending', reason='waiting_for_observed_hrf_tail',
                        earliest_sample_time_for_score_s=ready_at)
        # Future declared blocks have no regressors until their onset is sampled.
        active = [b for b in self.blocks if b['onset_s'] <= valid[-1]['sample_time_s']]
        times = np.array([r['sample_time_s'] for r in valid])
        columns = [block_regressor(times, b['onset_s'], b['duration_s'], self.hrf_dt_s) for b in active]
        drift = (times-times.mean())/max(np.ptp(times), 1.)
        columns += [np.ones(len(times)), drift]
        if self.include_motion:
            columns += list(np.array([r['motion'] for r in valid]).T)
        design = np.column_stack(columns)
        p = design.shape[1]
        if len(times)-p < self.min_residual_df:
            return dict(output, status='pending', reason='insufficient_residual_degrees_of_freedom')
        y = np.array([r['roi'] for r in valid])
        betas, _, rank, singular = np.linalg.lstsq(design, y, rcond=None)
        if rank < p:
            return dict(output, status='unestimable', reason='rank_deficient_design', rank=int(rank), columns=p)
        index = next(i for i, b in enumerate(active) if b['block_id'] == block_id)
        residual = y-design@betas
        df = len(times)-p
        covariance = residual.T@residual/df
        pinv = np.linalg.pinv(design)
        leverage = float(np.dot(pinv[index], pinv[index]))
        paired_residual = residual[:, 0]-residual[:, 1]
        variance = float(paired_residual@paired_residual/df*leverage)
        return dict(output, status='ok', reason=None, beta_difference=float(betas[index, 0]-betas[index, 1]),
            variance=max(variance, 0.), roi_betas=betas[index].tolist(),
            roi_beta_variances=(np.diag(covariance)*leverage).tolist(),
            roi_beta_covariance=float(covariance[0, 1]*leverage), residual_df=int(df),
            n_regressors=p, condition_number=float(singular[0]/singular[-1]),
            available_time_s=now, latest_input_available_time_s=valid[-1]['available_time_s'],
            latest_sample_time_s=float(times[-1]), fit_revision=len(rows),
            design_hash=_hash(dict(blocks=active, samples=[dict(volume_id=r['volume_id'],
                sample_time_s=r['sample_time_s'], motion=r['motion']) for r in valid])),
            limitations=['Unwhitened iid OLS variance; temporal autocorrelation is not modelled',
                         'ROI extraction, signal scaling, hardware clock calibration and spatial specificity are external'])
