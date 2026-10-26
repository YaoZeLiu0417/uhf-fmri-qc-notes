import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from experiments.interoception.roi_input import extract_roi_input


def write(path, data, affine=None):
    nib.save(nib.Nifti1Image(np.asarray(data, dtype=np.float32),
                            np.eye(4) if affine is None else affine), path)
    return path


def baseline(**changes):
    return dict(dict(baseline_id='synthetic_independent_rest_v1',
                     role='independent_baseline', frozen=True,
                     means={'III': 100., 'IV': 200.}), **changes)


def inputs(tmp_path):
    data = np.full((4, 4, 4), 100.)
    data[0, 0, 0], data[1, 0, 0], data[3, 3, 3] = 110., 130., 180.
    iii_l, iii_r, iv = (np.zeros_like(data) for _ in range(3))
    iii_l[0, 0, 0] = iii_r[1, 0, 0] = 3
    iv[3, 3, 3] = 4
    return (write(tmp_path/'volume.nii.gz', data),
            [write(tmp_path/'III_l.nii.gz', iii_l), write(tmp_path/'III_r.nii.gz', iii_r)],
            [write(tmp_path/'IV.nii.gz', iv)])


def extract(args, **kwargs):
    return extract_roi_input(*args, baseline=kwargs.pop('baseline', baseline()),
                             space_id=kwargs.pop('space_id', 'synthetic_shared_grid_v1'), **kwargs)


def test_nonunit_labels_hemisphere_union_and_frozen_independent_psc(tmp_path):
    args = inputs(tmp_path)
    result = extract(args)
    assert result['roi_order'] == ['III', 'IV']
    assert result['roi_values'] == pytest.approx([20., -10.])
    assert result['regions']['III']['raw_mean'] == 120.
    assert result['regions']['III']['voxel_count'] == 2
    assert result['regions']['IV']['raw_mean'] == 180.
    assert result['regions']['IV']['voxel_count'] == 1
    assert len(result['regions']['III']['mask_sha256']) == 2
    assert result['grid']['header_units'] == ['unknown', 'unknown']
    assert result['registration_performed'] is False
    assert result['preprocessing_performed'] is False
    assert result['real_time_performance_validated'] is False
    encoded = json.dumps(result, allow_nan=False)
    assert str(tmp_path) not in encoded
    assert len(result['source_volume_sha256']) == len(result['definition_hash']) == 64


def test_definition_is_stable_across_task_volumes_and_mask_order(tmp_path):
    args = inputs(tmp_path)
    first = extract(args)
    reordered = extract((args[0], list(reversed(args[1]))+args[1], args[2]))
    assert first['definition_hash'] == reordered['definition_hash']
    image = nib.load(args[0]); data = image.get_fdata()+5.
    other = write(tmp_path/'another_volume.nii.gz', data)
    second = extract((other, args[1], args[2]))
    assert first['source_volume_sha256'] != second['source_volume_sha256']
    assert first['definition_hash'] == second['definition_hash']
    third = extract(args, baseline=baseline(means={'III': 120., 'IV': 200.}))
    assert third['roi_definition_hash'] == first['roi_definition_hash']
    assert third['definition_hash'] != first['definition_hash']
    assert third['regions']['III']['psc'] == 0.


@pytest.mark.parametrize('bad', [None, {}, baseline(role='development'), baseline(frozen=False),
    baseline(baseline_id=''), baseline(means={'III': 100.}),
    baseline(means={'III': 0., 'IV': 200.}),
    baseline(means={'III': float('nan'), 'IV': 200.}),
    baseline(means={'III': True, 'IV': 200.})])
def test_baseline_is_never_inferred_from_current_task_data(tmp_path, bad):
    with pytest.raises(ValueError):
        extract(inputs(tmp_path), baseline=bad)


@pytest.mark.parametrize('bad', ['shifted_affine', 'different_shape', 'overlap',
    'empty_mask', 'negative_mask', 'nan_mask', 'nan_volume', '4d_volume'])
def test_invalid_inputs_are_rejected_without_registration_or_imputation(tmp_path, bad):
    volume, iii, iv = inputs(tmp_path)
    if bad == 'shifted_affine':
        aff = np.eye(4); aff[0, 3] = .01
        iii = [write(tmp_path/'shift.nii.gz', nib.load(iii[0]).get_fdata(), aff)]
    elif bad == 'different_shape':
        iii = [write(tmp_path/'wrong_shape.nii.gz', np.ones((3, 4, 4))*3)]
    elif bad == 'overlap':
        iv = iii
    elif bad == 'empty_mask':
        iii = [write(tmp_path/'empty.nii.gz', np.zeros((4, 4, 4)))]
    elif bad in ('negative_mask', 'nan_mask'):
        values = nib.load(iii[0]).get_fdata()
        values[2, 2, 2] = -1 if bad == 'negative_mask' else np.nan
        iii = [write(tmp_path/'bad_mask.nii.gz', values)]
    elif bad == 'nan_volume':
        values = nib.load(volume).get_fdata(); values[2, 2, 2] = np.nan
        volume = write(tmp_path/'nan_volume.nii.gz', values)
    elif bad == '4d_volume':
        volume = write(tmp_path/'4d.nii.gz', np.ones((4, 4, 4, 1)))
    with pytest.raises(ValueError):
        extract((volume, iii, iv))


def test_empty_mask_collection_and_undeclared_space_are_rejected(tmp_path):
    volume, iii, iv = inputs(tmp_path)
    with pytest.raises(ValueError):extract((volume, [], iv))
    with pytest.raises(ValueError):extract((volume, iii, iv), space_id='')
