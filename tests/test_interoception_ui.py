"""Rendering checks for information that could invalidate the manipulation."""
from experiments.interoception.ui import participant_card, operator_card, FAMILIES, FIELD
import numpy as np
import pytest


def test_feedback_source_and_algorithm_metadata_never_change_participant_artwork():
    view=dict(phase='task',is_synthetic=True,stimulus=dict(kind='feedback_ring',active=True))
    current=participant_card(dict(view,linkage='current',roi_score=9,heart_rate=70))
    replay=participant_card(dict(view,linkage='replay',roi_score=-2,heart_rate=95))
    assert current.tobytes()==replay.tobytes()
    # Both source conditions use an achromatic cue and identical background.
    assert current.getpixel((640,400))==(255,255,255)
    assert current.getpixel((600,400))==(0,0,0)


def test_no_feedback_attention_field_only_has_central_fixation_and_demo_label():
    im=participant_card(dict(phase='task',is_synthetic=True,stimulus={'kind':'fixation'}))
    assert set(map(tuple,np.unique(np.asarray(im.crop((0,150,1280,800))).reshape(-1,3),axis=0)))=={(0,0,0),(255,255,255)}
    # A second visible heartbeat reference would violate this spatial check.
    assert not np.asarray(im.crop((100,200,550,700))).any()
    assert not np.asarray(im.crop((730,200,1180,700))).any()


def test_no_default_answer_is_distinct_from_button_choice_and_launcher_targets_match_cards():
    base=dict(phase='synchrony',is_synthetic=True)
    missing=participant_card(dict(base,rating=dict(value=None,confirmed=False)))
    chosen=participant_card(dict(base,rating=dict(value=1,confirmed=True)))
    assert missing.tobytes()!=chosen.tobytes()
    image,hits=operator_card()
    assert image.size==(1280,800)
    assert set('family:'+f for f in FAMILIES)<=hits.keys()
    for key,(x0,y0,x1,y1) in hits.items():
        assert 0<=x0<x1<=1280 and 0<=y0<y1<=800


def test_psychopy_texture_uses_pil_path_preserving_levels_and_orientation():
    from PIL import Image
    from experiments.interoception.run_presentation import _texture
    image=participant_card(dict(phase='task',is_synthetic=True,stimulus={'kind':'fixation'}))
    texture=_texture(image)
    assert isinstance(texture,Image.Image) and texture.mode=='RGB'
    assert texture.getpixel((640,400))==(255,255,255)
    assert texture.getpixel((640,700))==(0,0,0)
    assert texture.tobytes()==image.tobytes()


@pytest.mark.parametrize('change',['condition','clock','provenance'])
def test_presenter_refuses_mislabelled_task_before_importing_gui(change):
    from types import SimpleNamespace
    from experiments.interoception.presentation import TaskPresentation
    from experiments.interoception.run_presentation import present_block
    flow=TaskPresentation(dict(condition_id='a',family='heartbeat_attention'),clock_id='task')
    bridge=SimpleNamespace(clock_id='wrong' if change=='clock' else 'task',is_synthetic=change!='provenance')
    command={'condition_id':'wrong' if change=='condition' else 'a'}
    with pytest.raises(ValueError,match='match the block command'):
        present_block(None,None,None,flow,bridge,command,event_sink=lambda event:None)


def test_only_two_semantic_participant_buttons_and_separate_trigger():
    from pathlib import Path
    from experiments.interoception.run_presentation import load_button_mapping
    cfg,keys=load_button_mapping(Path(__file__).parents[1]/'experiments/interoception/button_mapping.template.json')
    assert keys['1']=='1' and keys['2']=='2' and keys['num_1']=='1'
    assert keys['5']=='trigger' and keys['escape']=='escape'
    assert not {'3','4','space','left','right','u'} & keys.keys()
    assert cfg['mapping_status']=='unverified_demo_defaults'


def test_response_key_cannot_also_be_a_scanner_trigger(tmp_path):
    import json
    from pathlib import Path
    from experiments.interoception.run_presentation import load_button_mapping
    cfg=json.loads((Path(__file__).parents[1]/'experiments/interoception/button_mapping.template.json').read_text())
    cfg['simulated_trigger']=['1'];path=tmp_path/'mapping.json';path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='separate'):
        load_button_mapping(path)
