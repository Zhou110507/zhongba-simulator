"""Editable benchmark tasks; these expose no stored solutions to the solver."""
from .cue import ShotInput
from .model import Ball, Vec2


def example(service, kind):
    if kind not in ('one_bank', 'two_bank'): raise ValueError('未知碰库示例')
    balls = tuple(Ball(name, Vec2(x, y), spec=service.ball_spec) for name, x, y in
                  (('cue', .55, .5), ('1', 1.65, .65), ('2', 1.05, .55)))
    one = kind == 'one_bank'
    return {'scene': service.snapshot(balls, ShotInput(0, 1)), 'target': '1',
            'goal': {'x': 1.106 if one else .628, 'y': .196 if one else .662, 'radius': .08},
            'approach': kind, 'first_rail': 'top', 'second_rail': 'any' if one else 'right',
            'post_banks': None, 'pocket': None, 'max_cushions': 4, 'allow_other': False,
            'seconds': 25, 'evaluations': 1000, 'stability': 'full'}
