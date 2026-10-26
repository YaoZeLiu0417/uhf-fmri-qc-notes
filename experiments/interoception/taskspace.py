"""Load an explicit task registry without inventing distances between task labels."""
import json
from pathlib import Path
import numpy as np
from .contracts import fingerprint


def load_taskspace(path):
    cfg=json.loads(Path(path).read_text(encoding='utf-8'))
    if cfg.get('schema_version')!='interoception-taskspace-v0.2' or not isinstance(cfg.get('is_synthetic'),bool):
        raise ValueError('Explicit task-space version and provenance required')
    if not cfg['is_synthetic']:
        required=('independent_embedding_id','normalization_id','roi_definition_id','calibration_id')
        if any(not cfg.get(k) for k in required) or cfg.get('status')!='site_stream_dry_run' or cfg.get('optimizer_parameter_status')!='independently_calibrated_frozen':
            raise ValueError('A real-site dry run requires independently frozen space, ROI and calibration definitions')
    rows=cfg.get('conditions',[])
    if not rows or len({r['condition_id'] for r in rows})!=len(rows):
        raise ValueError('Unique conditions required')
    coords={r['condition_id']:r['coordinates'] for r in rows}
    try:x=np.asarray(list(coords.values()),dtype=float)
    except (TypeError,ValueError) as exc:raise ValueError('Independent coordinates have not been filled') from exc
    if x.ndim!=2 or not x.shape[1] or not np.isfinite(x).all() or np.any((x<0)|(x>1)):
        raise ValueError('Coordinates must be frozen finite vectors normalized to [0,1]')
    if not all(isinstance(r.get('family'),str) and r['family'] for r in rows):
        raise ValueError('Task family metadata required')
    plan=cfg.get('fixed_test_plan',[])
    if not plan or any(c not in coords for c in plan):
        raise ValueError('A predefined independent test plan is required')
    cfg['definition_sha256']=fingerprint(cfg)
    return cfg
