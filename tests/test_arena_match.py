"""Exercise the CGI-independent game API, including persisted race-to results."""
from copy import deepcopy
from math import atan2, degrees
from pathlib import Path

import pytest

from billiards.cue import ShotInput
from billiards.game import GameStore
from billiards.model import Ball, Vec2
from billiards.play import APP_VERSION, PlayService


def act(games, game, name, **extra):
    return games.action(dict(id=game['id'], revision=game['revision'], action=name, **extra))


@pytest.mark.parametrize('race', [1, 3])
def test_full_strokes_score_once_and_respect_match_length(tmp_path, race):
    service = PlayService(table_profile='cbsa_2017')
    games = GameStore(service, tmp_path, compact=True)
    balls = [Ball(key, Vec2(x, y), spec=service.ball_spec) for key, x, y in (
        ('cue', 1.19, .44), ('1', 1.27, .22), ('8', 1.9, .64), ('9', .45, .8))]
    ghost_y = .22 + 2*service.ball_spec.radius
    angle = degrees(atan2(ghost_y - .44, 1.27 - 1.19)) % 360
    scene = service.snapshot(balls, ShotInput(angle, 1.1, 0, 0))
    game = games.new(dict(scenario='ai_custom', scene=scene, race_to=race, ai_player=0))
    game = act(games, game, 'finish_setup', scene=scene, ai_player=0, ai_group='solid')
    game = act(games, game, 'set_ai', ai_player=None)
    def shoot(angle, speed):
        shot = dict(angle_deg=angle, cue_speed=speed, tip_x=0, tip_y=0)
        result = act(games, game, 'shoot', shot=shot)
        assert result['rule_committed'] and result['complete']
        return result['game_after']

    initial = deepcopy(game)
    preview = games.preview(dict(id=game['id'], revision=game['revision'], shot=scene['shot']))
    assert preview['complete'] and preview['summary']['potted'] == ['1'], preview['summary']
    assert games.get(dict(id=game['id']))['revision'] == game['revision']
    game = shoot(angle, 1.1)
    assert game['turn'] == 0 and game['phase'] == 'playing', game['last_decision']
    with pytest.raises(ValueError, match='对局已更新'):
        act(games, initial, 'shoot', shot=scene['shot'])
    game = shoot(2, .25)
    assert game['ball_in_hand'] == 'all' and game['turn'] == 1
    game = act(games, game, 'place', x=.55, y=.7)
    game = shoot(90, .25)
    assert game['ball_in_hand'] == 'all' and game['turn'] == 0
    black = next(b['position'] for b in game['scene']['balls'] if b['id'] == '8')
    dx, dy = service.table.length-black['x'], service.table.width-black['y']
    length = (dx*dx+dy*dy)**.5
    ux, uy = dx/length, dy/length
    gx, gy = black['x']-2*service.ball_spec.radius*ux, black['y']-2*service.ball_spec.radius*uy
    x, y = gx-.26*ux-.06*uy, gy-.26*uy+.06*ux
    game = act(games, game, 'place', x=x, y=y)
    game = shoot(degrees(atan2(gy-y, gx-x)) % 360, 1.3)
    assert game['phase'] == 'finished' and game['scores'] == [1, 0], game['last_decision']
    assert len(game['history']) == 4
    reloaded = GameStore(service, tmp_path).get(dict(id=game['id']))
    assert reloaded['scores'] == game['scores'] and reloaded['race_to'] == race
    if race == 1:
        assert reloaded['match_winner'] == 0
        with pytest.raises(ValueError, match='抢局已结束'):
            act(games, game, 'next_rack')
    else:
        assert reloaded['match_winner'] is None
        following = act(games, game, 'next_rack')
        assert following['rack_number'] == 2 and following['scores'] == game['scores']


def test_legacy_match_remains_continuous_and_target_is_validated(tmp_path):
    service = PlayService(table_profile='cbsa_2017')
    games = GameStore(service, tmp_path)
    g = games.new(dict(seed=4))
    state = games.games[g['id']]
    state.pop('race_to')
    assert games.public(state)['race_to'] == 0 and games.public(state)['match_winner'] is None
    for value in (-1, 22, True, 2.2):
        with pytest.raises(ValueError):
            games.new(dict(race_to=value))


def test_arena_document_build_matches_server_and_controls_have_unique_ids():
    from html.parser import HTMLParser
    class Shell(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.slots, self.assets, self.build = [], [], [], None
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if 'id' in values:
                self.ids.append(values['id'])
            if 'data-slot' in values:
                self.slots.append(values['data-slot'])
            if values.get('name') == 'arena-version':
                self.build = values['content']
            for key in ['src', 'href']:
                path = values.get(key, '')
                if path.startswith('/assets/'):
                    self.assets.append(path.removeprefix('/assets/'))
    shell = Shell()
    web = Path(__file__).resolve().parents[1] / 'web'
    shell.feed((web/'index.html').read_text(encoding='utf-8'))
    assert shell.build == APP_VERSION
    assert len(set(shell.ids)) == len(shell.ids)
    assert all(slot in shell.ids for slot in shell.slots)
    assert all((web/name).is_file() for name in shell.assets)
