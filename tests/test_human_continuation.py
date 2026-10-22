from copy import deepcopy
import json
import gzip
import hashlib
from pathlib import Path
import numpy as np
import pytest

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.model import Ball,Vec2
from billiards.play import PlayService
from billiards.runout import Search
from billiards.shot_prior import ShotPrior,contact_cost,continuation_cost
from billiards.tactics import direct_contact_rays,contact_candidates,opponent_threat,safety_checks


@pytest.fixture(scope='module')
def service():return PlayService(table_profile='cbsa_2017')


def board(service,blocker_y=None):
    state=GameStore(service).new({'scenario':'ai_endgame'})
    points=[('cue',.4,.6),('1',1.5,.6),('8',2.,1.)]
    if blocker_y is not None:points.append(('9',.9,blocker_y))
    state['scene']=service.snapshot([Ball(i,Vec2(x,y),spec=service.ball_spec) for i,x,y in points],ShotInput(0,1.))
    return state


def test_visible_ball_is_direct_even_without_any_pot_options(service,monkeypatch):
    state=board(service)
    monkeypatch.setattr('billiards.tactics.shot_options',lambda *a:[])
    assert direct_contact_rays(service,state)
    search=Search(service,trained=False,seconds=12,evaluations=20)
    rows=contact_candidates(service,state,search,attempts=8)
    assert rows and any(r['legal'] for r in rows)
    assert all(r['first_contact_cushions']==0 for r in rows)


def test_occluded_centre_with_visible_edge_does_not_require_escape(service):
    state=board(service,.655)
    # Centre ray is blocked (55 mm < 57.15 mm); legal edge rays still exist.
    rays=direct_contact_rays(service,state)
    assert rays and all(r['rails']==0 for r in rays)
    assert all(abs(r['angle'])>.1 for r in rays)


def test_fully_obscured_target_requires_escape(service):
    assert direct_contact_rays(service,board(service,.6))==[]


def test_defense_assesses_the_opponents_pocket_lines_not_our_own_options(service):
    state=board(service)
    # From this white ball, the opponent's nine is a short, straight shot into
    # the bottom-middle pocket. Our own one has no bearing on that threat.
    state['scene']=service.snapshot([Ball(i,Vec2(x,y),spec=service.ball_spec) for i,x,y in
        [('cue',1.27,.7),('9',1.27,.32),('1',.3,.9),('8',2.1,1.0)]],ShotInput(0,1.))
    check=opponent_threat(service,state,state['turn'],Search(service).policy)
    assert check['easy_options']>=1 and '9' in check['easy_targets']
    changed=deepcopy(state)
    next(b for b in changed['scene']['balls'] if b['id']=='9')['pocket']='bottom-middle'
    # With the nine gone the opponent is on black; that may itself be open.
    # Do not confuse the opponent's black-eight option with our own one.
    assert set(opponent_threat(service,changed,state['turn'],Search(service).policy)['easy_targets'])<= {'8'}


def test_safety_checks_record_real_legality_and_do_not_claim_unrun_probes(service):
    state=board(service)
    search=Search(service,trained=False,seconds=10,evaluations=20)
    shot=ShotInput(0,1.1,0,0);trial=search.forward(state,shot)
    assert trial and not trial[1]['last_decision']['fouls']
    from dataclasses import asdict
    rows=[{'shot':asdict(shot),'after':trial[1]}]
    count=safety_checks(service,state,rows,cancelled=lambda:False)
    check=rows[0]['safety_check']
    assert check['complete'] and check['checked']==check['legal']==4 and count==4
    cancelled_rows=[{'shot':asdict(shot),'after':trial[1]}]
    assert safety_checks(service,state,cancelled_rows,cancelled=lambda:True)==0
    assert not cancelled_rows[0]['safety_check']['complete'] and cancelled_rows[0]['safety_check']['checked']==0


def test_prior_search_with_no_pot_options_is_an_ordinary_not_found(service,monkeypatch):
    monkeypatch.setattr('billiards.runout.shot_options',lambda *a:[])
    result=Search(service,seconds=3,evaluations=10).solve(board(service))
    assert result['status']=='not_found' and result['evaluations']==0


def test_contacts_are_a_cost_even_when_opening_a_useful_ball():
    assert contact_cost([],'1',[])==0
    incidental=contact_cost([['cue','9']],'1',[])
    breakout=contact_cost([['cue','9']],'1',['2'])
    assert incidental>breakout>0
    assert contact_cost([['cue','9'],['cue','10']],'1',[])>incidental
    assert continuation_cost([],False)>continuation_cost([{'cost':1.,'rear_restricted':False}],False)>0
    assert continuation_cost([],True)==0


def test_exact_repeat_reuses_physics_but_changed_table_cannot(service):
    fixture=json.loads((Path(__file__).parent/'fixtures'/'ai-invalid-final-state.json').read_text(encoding='utf8'))
    state=fixture['candidate'];search=Search(service,trained=False,seconds=20,evaluations=20)
    shot=ShotInput(0,.5,0,.5)
    a=search.forward(state,shot);b=search.forward(state,shot)
    assert a and b and a[1]==b[1] and search.count==1 and search.reused_simulations==1
    changed=deepcopy(state);next(b for b in changed['scene']['balls'] if b['id']=='8')['position']['x']-=.015
    assert search.forward(changed,shot) and search.count==2


def test_prior_training_uses_disjoint_layouts_and_reports_heldout_top_four(service):
    model=ShotPrior(service);metrics=model.data['training']['metrics']
    assert model.predict([]).shape==(0,)
    seeds=[set(metrics[k]['seeds']) for k in ('train','validation','test')]
    assert all(not a&b for i,a in enumerate(seeds) for b in seeds[i+1:])
    # The wide-leaf objective differs from v8. Keep the honest held-out
    # comparison; candidate ordering is no longer allowed to prune the search.
    assert 0<=metrics['test']['top4_utility']<=metrics['test']['oracle_utility']
    assert 0<=metrics['test']['baseline_top4_utility']<=metrics['test']['oracle_utility']
    raw=gzip.decompress((service.root/'training'/'ai_stage5'/'shot-prior-dataset.json.gz').read_bytes())
    assert hashlib.sha256(raw).hexdigest()==model.data['training']['dataset_sha256']
    data=json.loads(raw.decode('utf8'))
    assert data['layouts']==288 and data['simulations']>15000
    assert data['leaf_margin_checked'] and all(r.get('leaf_passed',3)>=3 for r in data['rows'] if r['y']>0)
    values=model.predict([r['x'] for r in data['rows'][:12]])
    assert len(values)==12 and np.all(np.isfinite(values)) and np.all((values>=0)&(values<=1))
