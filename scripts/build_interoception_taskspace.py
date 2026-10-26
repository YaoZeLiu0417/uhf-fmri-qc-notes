"""Generate an explicit uncalibrated site template and a labelled toy GP space."""
from pathlib import Path
import copy
import json

ROOT=Path(__file__).resolve().parents[1]
FAMILIES=[
 ('heartbeat_attention','关注自身心跳','attention'),
 ('respiration_attention','关注自然呼吸','attention'),
 ('visual_rhythm','外部视觉节律判断','visual_rhythm'),
 ('body_feedback_synchrony','身体与反馈同步感判断','body_feedback'),
 ('gradcpt_standard','GradCPT普通动作映射','gradcpt'),
 ('gradcpt_reversed','GradCPT反转动作映射','gradcpt')]


def main():
    rows=[]
    for i,(family,label,plugin) in enumerate(FAMILIES):
        for j in range(3):
            rows.append(dict(condition_id=f'{family}_p{j+1}',family=family,label=label,
                preset_id=f'p{j+1}',coordinates=None,parameter_values=None,presentation_plugin=plugin,
                implementation_status='proposed_task_preset_requires_calibration_and_presenter',
                preset_interpretation='Family-specific candidate settings, not comparable difficulty units'))
    common=dict(schema_version='interoception-taskspace-v0.2',is_synthetic=False,
        status='pending_independent_pilot',clock_id='site_task_monotonic',
        independent_embedding_id=None,normalization_id=None,roi_definition_id=None,calibration_id=None,
        target='Candidate task-evoked BOLD difference between predefined Region III and IV',
        interpretation='Not a validated pure interoception, cardiac-phase or directed-connectivity score',
        source_paper='https://doi.org/10.1038/s41586-026-11175-2',
        source_mask_repository='https://github.com/LBCN-Stanford/Nature2026/tree/6072003b285a0dc39912c340f80a56a5098a7c76',
        source_mask_space='MNI152 ICBM 2009c nonlinear asymmetric, as declared by authors',
        optimizer=dict(burn_in=5,length_scale=[.22,.22],signal_variance=1.,noise_variance=.04,ucb_kappa=2.,ei_xi=.01),
        optimizer_parameter_status='Toy defaults, replace with independently calibrated frozen parameters before site use',
        glm=dict(hrf_tail_s=32.,hrf_dt_s=.1,include_motion=False,min_residual_df=4),
        glm_timing_status='Full 32-second tail is a conservative prototype rule, not original Lorenz timing',
        conditions=rows,fixed_test_plan=[r['condition_id'] for r in rows])
    folder=ROOT/'experiments/interoception'
    (folder/'taskspace.site_template.json').write_text(json.dumps(common,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sim=copy.deepcopy(common);sim.update(is_synthetic=True,status='simulation',clock_id='synthetic_task_monotonic',
        roi_definition_id='synthetic_region_III_IV_psc_v02',independent_embedding_id='toy_coordinates_not_empirical',
        normalization_id='synthetic_unit_square',calibration_id='synthetic_parameters_only')
    centers=[(.13,.22),(.25,.35),(.78,.24),(.39,.64),(.76,.78),(.60,.85)]
    for r in sim['conditions']:
        i=next(i for i,f in enumerate(FAMILIES) if f[0]==r['family']);j=int(r['preset_id'][-1])-2
        x,y=centers[i];r['coordinates']=[round(x+.035*j,3),round(y+.045*j,3)]
        r['parameter_values']={'synthetic_preset':j+2};r['implementation_status']='synthetic_controller_integration_only'
    sim['coordinates_interpretation']='Artificial geometry for software tests, not measured task relationships or an insula manifold'
    (folder/'taskspace.synthetic.json').write_text(json.dumps(sim,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Wrote 18-condition site template and a separate synthetic GP space')


if __name__=='__main__':main()
