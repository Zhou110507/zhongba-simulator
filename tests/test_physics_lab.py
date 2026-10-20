from math import sin, radians
from copy import deepcopy

import pytest

from billiards.play import PlayService
from billiards.physics_lab import run_experiment


@pytest.fixture(scope='module')
def service():return PlayService()


@pytest.mark.parametrize('kind,cut,follow,side',[
    ('ball',30,0,0),('ball',0,0,.5),('ball',30,0,.5),('ball',30,1,0),
    ('ball',6,-1,0),('cushion',30,1,.5)])
def test_every_lab_experiment_completes_and_leaves_the_current_scene_unchanged(service,kind,cut,follow,side):
    model=deepcopy(service.model)
    output=run_experiment(service,dict(kind=kind,speed=1.341,cut=cut,follow=follow,side=side))
    assert all(v['complete'] for v in output['variants'])
    assert all(v['metrics']['contact_energy_loss_J']>=-1e-10 for v in output['variants'])
    assert service.model==model
    if kind=='ball':
        assert output['variants'][1]['metrics']['throw_angle_deg']==pytest.approx(0,abs=1e-8)
        if side==sin(radians(cut)):
            assert output['variants'][0]['metrics']['throw_angle_deg']==pytest.approx(0,abs=1e-8)


@pytest.mark.parametrize('key,value',[('kind','unknown'),('speed',0),('speed',4),('speed',True),('cut',80),('follow',2),('side',float('inf'))])
def test_lab_rejects_nonphysical_or_unbounded_requests(service,key,value):
    data=dict(kind='ball',speed=1,cut=30,follow=0,side=0);data[key]=value
    with pytest.raises(ValueError):run_experiment(service,data)
