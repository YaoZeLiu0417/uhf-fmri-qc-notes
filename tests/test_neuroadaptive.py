import math
import numpy as np
import pytest

from experiments.interoception.neuroadaptive import NeuroadaptiveOptimizer


SPACE = {'low': [0.0], 'middle': [0.5], 'high': [1.0]}


def observation(block, condition, score, **kwargs):
    return dict(dict(run_id='run1', block_id=block, condition_id=condition,
                     value=score, role='development'), **kwargs)


def optimizer(**kwargs):
    return NeuroadaptiveOptimizer(SPACE, burn_in=0, **kwargs).reset('run1')


def test_gp_matches_a_closed_form_two_point_solution_and_uses_zero_mean():
    opt = optimizer(length_scale=1.0, signal_variance=1.0, noise_variance=.25)
    opt.fit([observation('b1', 'low', 1.0), observation('b2', 'high', -1.0)])
    post = opt.posterior()
    rho = math.exp(-.5)
    k = math.exp(-.125)
    assert post['middle']['mean'] == pytest.approx(0, abs=1e-12)
    assert post['middle']['sd']**2 == pytest.approx(1-2*k*k/(1.25+rho))
    assert post['low']['mean'] == pytest.approx((1-rho)/(1.25-rho))
    assert opt.suggest()['model']['y_centered'] is False


def test_noiseless_training_point_interpolates_and_repeated_condition_blocks_remain_distinct():
    opt = optimizer(noise_variance=0.0)
    opt.fit([observation('b1', 'middle', 2.5)])
    assert opt.posterior()['middle']['mean'] == pytest.approx(2.5, abs=1e-12)
    assert opt.posterior()['middle']['sd'] < 1e-7
    opt.fit([observation('b1', 'middle', 2.5), observation('b2', 'middle', 2.5)])
    assert opt.suggest()['n_observations'] == 2
    assert opt.suggest()['model']['numerical_jitter'] > 0


def test_snapshot_replaces_old_glm_betas_instead_of_appending_them():
    opt = optimizer(noise_variance=.1)
    opt.fit([observation('b1', 'low', 1.0)])
    opt.fit([observation('b1', 'low', 3.0), observation('b2', 'high', 2.0)])
    fresh = optimizer(noise_variance=.1).fit([observation('b1', 'low', 3.0), observation('b2', 'high', 2.0)])
    assert opt.suggest()['n_observations'] == 2
    assert opt.posterior() == fresh.posterior()
    opt.fit([])
    assert opt.suggest()['n_observations'] == 0
    assert all(p['mean'] == 0 and p['sd'] == 1 for p in opt.posterior().values())


def test_burn_in_is_seeded_without_replacement_and_reset_clears_the_run():
    opt = NeuroadaptiveOptimizer(SPACE, burn_in=3, seed=17).reset('run1')
    rows, sequence = [], []
    for i in range(3):
        choice = opt.suggest()
        assert choice == opt.suggest()
        assert choice['reason'] == 'random_burn_in_without_replacement'
        sequence.append(choice['condition_id'])
        rows.append(observation(f'b{i}', choice['condition_id'], 0.1*i))
        opt.fit(rows)
    assert len(set(sequence)) == 3
    assert opt.suggest()['reason'] == 'maximum_ei'
    opt.reset('run2')
    assert opt.suggest()['condition_id'] == sequence[0]
    assert opt.suggest()['n_observations'] == 0


def test_ei_uses_standard_deviation_and_gp_ucb_has_its_declared_formula():
    opt = optimizer(signal_variance=4.0)
    result = opt.suggest()
    assert all(c['posterior_sd'] == 2 for c in result['candidates'])
    assert all(c['acquisition'] == pytest.approx(2/math.sqrt(2*math.pi)) for c in result['candidates'])
    ucb = optimizer(acquisition='gp_ucb', ucb_kappa=2.5)
    ucb.fit([observation('b1', 'low', 1)])
    for row in ucb.suggest()['candidates']:
        assert row['acquisition'] == pytest.approx(row['posterior_mean']+2.5*row['posterior_sd'])
    assert ucb.suggest()['reason'] == 'maximum_gp_ucb'


def test_freeze_blocks_mutation_and_selection_and_reset_explicitly_unlocks():
    opt = optimizer().fit([observation('b1', 'low', 2)])
    before = opt.posterior()
    frozen = opt.freeze()
    assert frozen == opt.freeze()
    assert len(frozen['model_sha256']) == 64
    assert opt.posterior() == before
    with pytest.raises(ValueError, match='frozen'):
        opt.fit([])
    with pytest.raises(ValueError, match='frozen'):
        opt.suggest()
    opt.reset('run2')
    assert opt.suggest()['n_observations'] == 0


@pytest.mark.parametrize('change', [
    {'role': 'test'}, {'role': 'holdout'}, {'run_id': 'other_run'},
    {'value': np.nan}, {'value': np.inf}, {'value': True},
    {'variance': -1}, {'variance': np.inf}, {'variance': None},
    {'condition_id': 'unregistered'}, {'block_id': ''},
])
def test_invalid_observations_and_test_data_cannot_change_a_prior_valid_snapshot(change):
    opt = optimizer().fit([observation('b1', 'low', 1)])
    before = opt.posterior()
    with pytest.raises(ValueError):
        opt.fit([observation('b2', 'high', 2, **change)])
    assert opt.posterior() == before


def test_duplicate_block_ids_are_rejected_but_not_duplicate_conditions():
    opt = optimizer()
    with pytest.raises(ValueError, match='duplicate'):
        opt.fit([observation('b1', 'low', 1), observation('b1', 'high', 2)])
    opt.fit([observation('b1', 'low', 1), observation('b2', 'low', 2)])
    assert opt.suggest()['n_observations'] == 2


@pytest.mark.parametrize('kwargs', [
    {'length_scale': 0}, {'length_scale': [1, 2]}, {'noise_variance': -1},
    {'signal_variance': 0}, {'signal_variance': np.nan}, {'ucb_kappa': -1},
    {'ei_xi': np.inf}, {'acquisition': 'balanced'}, {'burn_in': -1},
])
def test_invalid_model_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        NeuroadaptiveOptimizer(SPACE, **kwargs)


@pytest.mark.parametrize('coords', [{}, {'a': [np.nan]}, {'a': [1.01]},
                                    {'a': [-.01]}, {'a': []}, {'a': [0], 'b': [0, 1]}])
def test_coordinate_validation_rejects_nonfinite_or_out_of_range_values(coords):
    with pytest.raises(ValueError):
        NeuroadaptiveOptimizer(coords)


def test_run_start_is_explicit_and_observation_variance_changes_posterior_precision():
    unstarted = NeuroadaptiveOptimizer(SPACE)
    with pytest.raises(ValueError, match='reset'):
        unstarted.suggest()
    low_noise = optimizer().fit([observation('b1', 'middle', 1, variance=.01)])
    high_noise = optimizer().fit([observation('b1', 'middle', 1, variance=1)])
    assert low_noise.posterior()['middle']['sd'] < high_noise.posterior()['middle']['sd']
