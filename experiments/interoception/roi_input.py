"""Extract two ROI streams from an already registered standalone 3D NIfTI.

This adapter checks numeric geometry; it does not identify anatomical space,
register/resample, preprocess, assess MRI quality, or validate real-time speed.
The site must independently establish its EPI/mask transforms and ``space_id``.
The official Quabs masks declare MNI2009c in the paper, but their header units
are unknown and their foreground labels are 3/4 rather than 1. Selection here
uses values > 0, not label == 1 or probability weighting. No source masks are
bundled with the code or assigned this repository's software licence.

PSC uses caller-supplied, frozen independent baseline means. Declared baseline
provenance is required, but its independence cannot be proved from means alone.
No baseline is estimated from the task volume. Returned metadata contains no
voxel arrays or identifying file paths and must remain in private session logs.
"""
import hashlib
import json
import math
import numbers
from os import PathLike
from pathlib import Path

import nibabel as nib
import numpy as np

AFFINE_ATOL = 1e-5


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _definition_hash(value):
    return _digest(json.dumps(value, sort_keys=True, allow_nan=False).encode('utf-8'))


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Explicit {label} required')
    return value


def _load(path):
    path = Path(path)
    if not str(path).lower().endswith(('.nii', '.nii.gz')):
        raise ValueError('A standalone .nii or .nii.gz file is required')
    before = _digest(path.read_bytes())
    try:
        image = nib.load(path)
    except nib.filebasedimages.ImageFileError as exc:
        raise ValueError('Cannot read the standalone NIfTI input') from exc
    data = np.asanyarray(image.dataobj)
    affine = image.affine
    if data.ndim != 3 or not np.isrealobj(data) or not np.isfinite(data).all():
        raise ValueError('Each input must be a finite real-valued 3D volume')
    if affine.shape != (4, 4) or not np.isfinite(affine).all() or abs(np.linalg.det(affine[:3, :3])) < 1e-12:
        raise ValueError('Finite nonsingular NIfTI affine required')
    if before != _digest(path.read_bytes()):
        raise ValueError('Input changed while it was being read')
    return image, data, before


def _mask_union(paths, reference_image):
    if isinstance(paths, (str, PathLike)):
        paths = [paths]
    else:
        paths = list(paths)
    if not paths:
        raise ValueError('At least one nonempty mask is required per region')
    union = np.zeros(reference_image.shape, dtype=bool)
    provenance = []
    for path in paths:
        image, values, digest = _load(path)
        if image.shape != reference_image.shape or not np.allclose(
                image.affine, reference_image.affine, rtol=0., atol=AFFINE_ATOL):
            raise ValueError('Volume and masks must already share shape and affine grid')
        selected = values > 0
        if np.any(values < 0) or not selected.any():
            raise ValueError('Each label mask must be nonnegative and nonempty')
        union |= selected
        provenance.append(dict(sha256=digest, shape=list(image.shape),
            affine=image.affine.tolist(), header_units=list(image.header.get_xyzt_units())))
    # Ordering and duplicate copies of the same hemisphere file do not change
    # the union or its definition. Geometric overlaps between III/IV are fatal.
    unique = {entry['sha256']: entry for entry in provenance}
    return union, [unique[key] for key in sorted(unique)]


def _baseline(baseline):
    if not isinstance(baseline, dict) or baseline.get('role') != 'independent_baseline' or baseline.get('frozen') is not True:
        raise ValueError('A frozen independent baseline declaration is required')
    baseline_id = _identifier(baseline.get('baseline_id'), 'baseline ID')
    means = baseline.get('means')
    if not isinstance(means, dict) or set(means) != {'III', 'IV'}:
        raise ValueError('Explicit independent means for III and IV required')
    result = {}
    for key, value in means.items():
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real) or not math.isfinite(value) or value <= 0:
            raise ValueError('Baseline means must be finite positive numbers')
        result[key] = float(value)
    return dict(baseline_id=baseline_id, role='independent_baseline', frozen=True, means=result)


def extract_roi_input(source_volume_path, region_iii_mask_paths, region_iv_mask_paths,
                      *, baseline, space_id):
    """Return PSC values in III/IV order plus source/definition provenance.

    ``baseline`` must explicitly declare ``baseline_id``,
    ``role='independent_baseline'``, ``frozen=True`` and positive independent
    ``means={'III': ..., 'IV': ...}``. This is an externally verified source
    declaration, not an estimate this function can validate independently.

    Masks may be single paths or lists of hemisphere paths. All inputs must
    already share one grid to absolute affine tolerance 1e-5 in declared
    coordinate units. Unknown header units remain unknown. The adapter never
    guesses a template, converts coordinates, fills missing voxels or fixes a
    mask. Caller-supplied acquisition/arrival times and QC must be added by the
    stream wrapper before calling IncrementalROIGLM.add_volume.
    """
    declared_baseline = _baseline(baseline)
    space_id = _identifier(space_id, 'site-verified space ID')
    image, values, source_sha256 = _load(source_volume_path)
    masks, inputs = {}, {}
    for region, paths in [('III', region_iii_mask_paths), ('IV', region_iv_mask_paths)]:
        masks[region], inputs[region] = _mask_union(paths, image)
    if np.any(masks['III'] & masks['IV']):
        raise ValueError('Region III and IV masks must not overlap')
    roi_definition = dict(schema_version='roi-mask-definition-v0.1',
        space_id=space_id, selection_rule='foreground_values_gt_zero_union',
        affine_atol=AFFINE_ATOL, regions=inputs)
    roi_hash = _definition_hash(roi_definition)
    definition_hash = _definition_hash(dict(roi_definition_hash=roi_hash,
        baseline=declared_baseline, scaling='100*(raw_mean/baseline_mean-1)'))
    regions = {}
    for key in ('III', 'IV'):
        mean = float(np.mean(values[masks[key]], dtype=np.float64))
        psc = 100. * (mean / declared_baseline['means'][key] - 1.)
        if not math.isfinite(mean) or not math.isfinite(psc):
            raise ValueError('Nonfinite ROI mean or percent signal change')
        regions[key] = dict(raw_mean=mean, psc=psc,
            voxel_count=int(masks[key].sum()), mask_sha256=[r['sha256'] for r in inputs[key]])
    return dict(schema_version='nifti-roi-input-v0.1', source_volume_sha256=source_sha256,
        space_id=space_id, grid=dict(shape=list(image.shape), affine=image.affine.tolist(),
            header_units=list(image.header.get_xyzt_units()),
            units_interpretation='Header declaration only; no anatomical space or physical unit is inferred'),
        roi_order=['III', 'IV'], roi_values=[regions[key]['psc'] for key in ('III', 'IV')],
        units='percent_signal_change', regions=regions, baseline=declared_baseline,
        roi_definition_hash=roi_hash, definition_hash=definition_hash,
        roi_definition=roi_definition, preprocessing_performed=False,
        registration_performed=False, real_time_performance_validated=False)
