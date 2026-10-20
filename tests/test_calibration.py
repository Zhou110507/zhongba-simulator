from copy import deepcopy

import pytest

from billiards.calibration import fit_measurements


def measurements():
    return {'schema_version':1,'source':'test-generated synthetic values, never real table measurements',
            'data_origin':'synthetic','records':[
                *[{'kind':'rolling_stop','speed_m_s':v,'distance_m':v*v/(2*9.81*.007)} for v in (.5,1,1.5)],
                *[{'kind':'slide_to_roll','speed_m_s':v,'radius_m':.028575,'forward_omega_rad_s':-v/.028575,
                   'time_s':2*v/(3.5*9.81*.18)} for v in (.6,1,1.5)],
                *[{'kind':'spin_decay','initial_abs_omega_rad_s':50,'final_abs_omega_rad_s':50-10*t,'time_s':t} for t in (1,2,3)],
                *[{'kind':'normal_ball_collision','approach_speed_m_s':v,'separation_speed_m_s':.95*v} for v in (.5,1,2)]]}


def test_independent_measurement_types_recover_known_parameters_and_preserve_raw_data():
    data=measurements();original=deepcopy(data)
    result=fit_measurements(data)
    assert result['parameters']==pytest.approx({'rolling_friction':.007,'sliding_friction':.18,'spin_deceleration':10,'ball_restitution':.95})
    assert all(e['residual_rms']<1e-12 for e in result['estimates'].values())
    assert data==original
    assert 'not_applied' in result['status'] and result['data_origin']=='synthetic'


def test_noisy_rolling_fit_predicts_a_held_out_stop_distance_with_documented_residual():
    data=measurements();data['records']=[r for r in data['records'] if r['kind']=='rolling_stop']
    for r,error in zip(data['records'],(.01,-.01,.005)):
        r['distance_m']*=1+error
    result=fit_measurements(data);estimate=result['estimates']['rolling_friction']
    assert estimate['residual_rms']>0
    prediction=1.2**2/(2*9.81*estimate['value'])
    assert prediction==pytest.approx(1.2**2/(2*9.81*.007),rel=.01)


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(schema_version=2),lambda d:d.update(records=[]),
    lambda d:d['records'][0].update(distance_m=0),lambda d:d['records'][0].update(speed_m_s=True),
    lambda d:d['records'][0].update(speed_m_s=float('nan')),
    lambda d:d['records'][0].update(speed_m_s=1e200),
    lambda d:d['records'][0].update(speed_m_s=10**1000),
    lambda d:d['records'][0].update(distance_m=1e-300),
    lambda d:d['records'][0].update(kind='cushion_speed_ratio'),
    lambda d:d['records'][-1].update(separation_speed_m_s=100),
    lambda d:d.update(records=d['records'][:1]),
])
def test_invalid_or_inapplicable_measurements_are_rejected(mutation):
    data=measurements();mutation(data)
    with pytest.raises(ValueError):fit_measurements(data)
