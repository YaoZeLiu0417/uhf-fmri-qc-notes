"""Discrete, zero-mean GP optimization for the proposed experiment prototype.

Pass independently defined coordinates scaled to [0, 1]. Hyperparameters stay
fixed within a run. This module implements actual GP regression and EI/GP-UCB,
not the earlier balanced fallback. It does not validate task-space geometry,
physiological accuracy, ROI specificity, hardware timing or human experiments.

``fit`` replaces the complete block snapshot. Re-estimated incremental-GLM
betas for existing block IDs therefore replace their old values rather than
becoming fictitious extra observations. Distinct blocks at the same condition
remain repeated measurements.

EI uses latent posterior *standard deviation* in its standard expression.
Uncertainty notation in the 2018 paper is not treated as a licence to substitute
variance for SD. These fixed hyperparameters and the posterior-mean incumbent
are explicit prototype choices, not an exact reproduction of original code.
"""
import hashlib
import json
import random

import numpy as np
from scipy.linalg import solve_triangular
from scipy.special import ndtr


def _number(value, name, *, minimum=None, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f'{name} must be a finite number')
    result = float(value)
    if not np.isfinite(result) or (positive and result <= 0) or (minimum is not None and result < minimum):
        raise ValueError(f'Invalid {name}')
    return result


class NeuroadaptiveOptimizer:
    """Sequential discrete GP search, with explicit run and freeze boundaries.

    Observation fields: run_id, block_id, condition_id, value,
    role='development'; variance optionally overrides the fixed observation
    noise variance. A snapshot may contain zero or more complete observations.
    Selection waits for a new snapshot; repeated suggest() calls are idempotent.
    """

    def __init__(self, coordinates, acquisition='ei', burn_in=5, seed=0,
                 length_scale=1.0, signal_variance=1.0, noise_variance=0.01,
                 ucb_kappa=2.0, ei_xi=0.0):
        if not isinstance(coordinates, dict) or not coordinates or not all(isinstance(k, str) and k for k in coordinates):
            raise ValueError('Nonempty condition IDs and coordinate vectors required')
        self.condition_ids = tuple(coordinates)
        try:
            x = np.array(list(coordinates.values()), dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid coordinates') from exc
        if x.ndim != 2 or not x.shape[1] or not np.isfinite(x).all() or np.any((x < 0) | (x > 1)):
            raise ValueError('Coordinates must be finite vectors within [0, 1]')
        x.setflags(write=False)
        self._x = x
        self._index = {key: i for i, key in enumerate(self.condition_ids)}
        if acquisition not in ('ei', 'gp_ucb'):
            raise ValueError('Acquisition must be ei or gp_ucb')
        if isinstance(burn_in, bool) or not isinstance(burn_in, int) or burn_in < 0:
            raise ValueError('burn_in must be a nonnegative integer')
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError('seed must be an integer')
        try:
            ell = np.array(length_scale, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid length scale') from exc
        if ell.ndim == 0:
            ell = np.full(x.shape[1], float(ell))
        if ell.shape != (x.shape[1],) or not np.isfinite(ell).all() or np.any(ell <= 0):
            raise ValueError('Length scale must be positive, finite and dimension-matched')
        ell.setflags(write=False)
        self._ell = ell
        self.acquisition = acquisition
        self.burn_in = min(burn_in, len(self.condition_ids))
        self.seed = seed
        self.signal_variance = _number(signal_variance, 'signal variance', positive=True)
        self.noise_variance = _number(noise_variance, 'noise variance', minimum=0)
        self.ucb_kappa = _number(ucb_kappa, 'UCB kappa', minimum=0)
        self.ei_xi = _number(ei_xi, 'EI xi', minimum=0)
        self.run_id = None
        self._frozen = False
        self._rows = ()
        self._chol = None
        self._alpha = None
        self._train_x = np.empty((0, x.shape[1]))
        self._jitter = 0.0

    def reset(self, run_id, seed=None):
        """Start a named independent run, clearing observations and freeze state."""
        if not isinstance(run_id, str) or not run_id:
            raise ValueError('Explicit run ID required')
        chosen_seed = self.seed if seed is None else seed
        if isinstance(chosen_seed, bool) or not isinstance(chosen_seed, int):
            raise ValueError('seed must be an integer')
        self.run_id = run_id
        self._active_seed = chosen_seed
        self._burn_order = tuple(random.Random(chosen_seed).sample(self.condition_ids, len(self.condition_ids)))
        self._rows = ()
        self._chol = self._alpha = None
        self._train_x = np.empty((0, self._x.shape[1]))
        self._jitter = 0.0
        self._frozen = False
        return self

    def _active(self, mutate=False):
        if self.run_id is None:
            raise ValueError('reset(run_id) must start a run first')
        if mutate and self._frozen:
            raise ValueError('Optimizer is frozen; start a new independent run with reset')

    def _kernel(self, a, b):
        distance = ((a[:, None, :] - b[None, :, :]) / self._ell) ** 2
        return self.signal_variance * np.exp(-0.5 * distance.sum(axis=2))

    def fit(self, observations):
        """Atomically replace history with a validated complete GLM snapshot."""
        self._active(mutate=True)
        rows, seen = [], set()
        for row in observations:
            if not isinstance(row, dict) or row.get('role') != 'development' or row.get('run_id') != self.run_id:
                raise ValueError('Only development observations from the current run may update the model')
            key = row.get('block_id')
            condition = row.get('condition_id')
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError('Empty or duplicate block ID in snapshot')
            if not isinstance(condition, str) or condition not in self._index:
                raise ValueError('Condition is outside the declared task space')
            value = _number(row.get('value'), 'observation value')
            variance = _number(row.get('variance', self.noise_variance), 'observation variance', minimum=0)
            seen.add(key)
            rows.append(dict(run_id=self.run_id, block_id=key, condition_id=condition,
                             value=value, variance=variance, role='development'))
        train_x = self._x[[self._index[r['condition_id']] for r in rows]]
        chol = alpha = None
        jitter = 0.0
        if rows:
            cov = self._kernel(train_x, train_x)
            with np.errstate(over='ignore', invalid='ignore'):
                cov[np.diag_indices_from(cov)] += [r['variance'] for r in rows]
            if not np.isfinite(cov).all():
                raise ValueError('Covariance overflow')
            scale = self.signal_variance
            for relative_jitter in (0.0, 1e-12, 1e-10, 1e-8, 1e-6):
                jitter = scale * relative_jitter
                try:
                    chol = np.linalg.cholesky(cov + np.eye(len(rows)) * jitter)
                    break
                except np.linalg.LinAlgError:
                    continue
            else:
                raise ValueError('Covariance remains unstable after numerical jitter')
            values = np.array([r['value'] for r in rows])
            alpha = solve_triangular(chol.T, solve_triangular(chol, values, lower=True), lower=False)
            if not np.isfinite(alpha).all():
                raise ValueError('Unstable observation scale')
        self._rows = tuple(rows)
        self._train_x, self._chol, self._alpha, self._jitter = train_x, chol, alpha, jitter
        return self

    def _prediction(self):
        mean = np.zeros(len(self.condition_ids))
        variance = np.full(len(self.condition_ids), self.signal_variance)
        if self._rows:
            cross = self._kernel(self._x, self._train_x)
            mean = cross @ self._alpha
            solved = solve_triangular(self._chol, cross.T, lower=True)
            variance -= np.einsum('ij,ij->j', solved, solved)
        if not np.isfinite(mean).all() or not np.isfinite(variance).all():
            raise ValueError('Nonfinite posterior')
        if variance.min() < -1e-8 * self.signal_variance:
            raise ValueError('Invalid negative posterior variance')
        return mean, np.sqrt(np.maximum(variance, 0.0))

    def posterior(self):
        """Read latent posterior means and SDs, including after freezing."""
        self._active()
        mean, sd = self._prediction()
        return {key: dict(mean=float(mean[i]), sd=float(sd[i])) for i, key in enumerate(self.condition_ids)}

    def suggest(self):
        """Choose one next condition, returning every candidate's model scores."""
        self._active(mutate=True)
        mean, sd = self._prediction()
        sampled = {r['condition_id'] for r in self._rows}
        incumbent = max((mean[self._index[c]] for c in sampled), default=0.0)
        if self.acquisition == 'ei':
            delta = mean - incumbent - self.ei_xi
            scores = np.maximum(delta, 0.0)
            positive = sd > 0
            with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                z = delta[positive] / sd[positive]
                scores[positive] = delta[positive] * ndtr(z) + sd[positive] * np.exp(-0.5 * z*z) / np.sqrt(2*np.pi)
            scores = np.maximum(scores, 0.0)
        else:
            scores = mean + self.ucb_kappa * sd
        if not np.isfinite(scores).all():
            raise ValueError('Nonfinite acquisition scores')
        if len(self._rows) < self.burn_in:
            chosen = next(c for c in self._burn_order if c not in sampled)
            reason = 'random_burn_in_without_replacement'
        else:
            chosen = self.condition_ids[int(np.argmax(scores))]
            reason = f'maximum_{self.acquisition}'
        candidates = [dict(condition_id=c, posterior_mean=float(mean[i]), posterior_sd=float(sd[i]), acquisition=float(scores[i]))
                      for i, c in enumerate(self.condition_ids)]
        return dict(run_id=self.run_id, condition_id=chosen, reason=reason,
                    n_observations=len(self._rows), candidates=candidates,
                    model=dict(kernel='squared_exponential', zero_mean=True,
                               y_centered=False, length_scale=self._ell.tolist(),
                               signal_variance=self.signal_variance, default_noise_variance=self.noise_variance,
                               acquisition=self.acquisition, ei_xi=self.ei_xi, ucb_kappa=self.ucb_kappa,
                               numerical_jitter=self._jitter, uncertainty='latent_posterior_standard_deviation',
                               ei_incumbent='best_posterior_mean_at_observed_conditions', seed=self._active_seed))

    def freeze(self):
        """Lock fitting/selection; reading posterior remains available."""
        self._active()
        content = dict(run_id=self.run_id, coordinates=dict(zip(self.condition_ids, self._x.tolist())),
                       observations=self._rows, length_scale=self._ell.tolist(),
                       signal_variance=self.signal_variance, noise_variance=self.noise_variance,
                       acquisition=self.acquisition, ei_xi=self.ei_xi, ucb_kappa=self.ucb_kappa,
                       zero_mean=True, y_centered=False, seed=self._active_seed, burn_in=self.burn_in)
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, allow_nan=False).encode()).hexdigest()
        self._frozen = True
        return dict(run_id=self.run_id, model_sha256=digest, n_observations=len(self._rows), frozen=True)
