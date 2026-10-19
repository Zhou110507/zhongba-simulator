"""Reproducible phase-A acceptance scenes, not a full cue-tip impact model."""

from dataclasses import replace
from pathlib import Path
from .equipment import load_equipment, load_physics_profile
from .model import Ball, Physics, Table, Vec2, Vec3

R = .028575


def acceptance_scenes():
    equipment = load_equipment(Path(__file__).resolve().parents[1]/"configs"/"chinese_eight_ball.json")
    table = equipment.table
    default = load_physics_profile(Path(__file__).resolve().parents[1]/"configs"/"physics_profiles.json")
    impact_time, speed, decel = .04, 1.5, .2*9.81
    distance = speed*impact_time-.5*decel*impact_time**2
    stun_omega = -2.5*decel*impact_time/R
    return [
        {"id": "slide", "name": "01 / 滑动 → 滚动 → 停止",
         "description": "白球以 0.7 m/s、无初始旋转出发。台呢摩擦产生前旋，随后纯滚动并停止。",
         "observe": "白球沿直线减速；轨迹和终点由物理模型计算。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(.35,.635),Vec2(.7,0))]},
        {"id": "draw", "name": "02 / 低杆：碰球后回拉",
         "description": "碰撞前保留后旋，白球碰到目标球后由剩余后旋产生回拉。",
         "observe": "碰撞后白球先失去大部分前进速度，随后向左回拉。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(.7,.635),Vec2(1.5,0),Vec3(0,-1.5/R,0)),
                   Ball("1",Vec2(.82,.635))]},
        {"id": "follow", "name": "03 / 高杆：碰球后跟进",
         "description": "与低杆场景使用相同位置和初速度，改为初始前旋。",
         "observe": "碰撞后白球继续向右跟进；不额外施加人工推动。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(.7,.635),Vec2(1.5,0),Vec3(0,1.5/R,0)),
                   Ball("1",Vec2(.82,.635))]},
        {"id": "stun", "name": "04 / 定杆：到碰撞时旋转归零",
         "description": "根据摩擦和球距设置初始后旋，令碰撞时水平旋转恰好归零。本例球球恢复系数设为 1，以隔离定杆基准。",
         "observe": "白球停在接触位置，目标球继续运动。",
         "table": table, "physics": replace(default,ball_restitution=1),
         "balls": [Ball("cue",Vec2(.7,.635),Vec2(speed,0),Vec3(0,stun_omega,0)),
                   Ball("1",Vec2(.7+distance+2*R,.635))]},
        {"id": "cut", "name": "05 / 薄厚球：斜向分离",
         "description": "白球和目标球初始角速度均为零。白球以 1.3 m/s 向右出发，台呢摩擦使球逐渐滚动；因此到碰库时已不是无旋转状态。两球均调用与 06 相同的碰库内核。",
         "observe": "逐球查看下库、上库和右库的碰前/碰后旋转与方向；可用 05B 对照完全无摩擦的几何反射。参数仍待实桌标定。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(.4,.59),Vec2(1.3,0)),
                   Ball("1",Vec2(1.1,.63))]},
        {"id": "cut_mirror", "name": "05B / 薄厚球：理想碰库对照",
         "description": "与 05 的位置、初速度和初始角速度相同，关闭台呢/库边摩擦，球球和球库碰撞均设为完全弹性。两球始终没有旋转。",
         "observe": "两颗球分别碰到上下库时，入射角等于反射角；这是数学对照，主动截断于 2.4 s，不是自然停球。",
         "table": table, "physics": replace(default,sliding_friction=0,rolling_friction=0,
                                              spin_deceleration=0,cushion_friction=0,
                                              ball_restitution=1,cushion_restitution=1),
         "max_time": 2.4, "expected_status": "max_time",
         "balls": [Ball("cue",Vec2(.4,.59),Vec2(1.3,0)),
                   Ball("1",Vec2(1.1,.63))]},
        {"id": "rail", "name": "06A / 碰库：自然滚动 + 侧旋",
         "description": "原 06 场景。位置 (1.8, 0.65) m，速度 (2.2, 0.7) m/s，ω=(-24.497, 76.990, 20) rad/s：自然滚动并额外带侧旋。",
         "observe": "碰库前直线；库边与台呢冲量改变三轴旋转，碰后接触点滑动产生弧线，恢复滚动后重新直行。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(1.8,.65),Vec2(2.2,.7),Vec3(-.7/R,2.2/R,20))]},
        {"id": "rail_no_side", "name": "06B / 碰库：自然滚动、无侧旋",
         "description": "与原 06 相同位置与速度，仅把 ωz 设为 0。自然滚动仍有 ωx、ωy，不能等同于完全无旋转。",
         "observe": "用于与 06A 比较侧旋；再与 06C 比较理想反射。库边摩擦也可能产生新的侧旋。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(1.8,.65),Vec2(2.2,.7),Vec3(-.7/R,2.2/R,0))]},
        {"id": "rail_mirror", "name": "06C / 碰库：无旋转理想反射",
         "description": "完全无旋转、无台呢和库边摩擦、完全弹性。这是验证入射角等于反射角的数学对照。",
         "observe": "全程直线分段，入射角与反射角相同。仅演示 0.8 s，主动截断；不是自然停球。",
         "table": table, "physics": replace(default,sliding_friction=0,rolling_friction=0,
                                              spin_deceleration=0,cushion_friction=0,
                                              cushion_restitution=1),
         "max_time": .8, "expected_status": "max_time",
         "balls": [Ball("cue",Vec2(1.8,.65),Vec2(2.2,.7))]},
        {"id": "spin", "name": "07 / 侧旋：与平动独立衰减",
         "description": "白球滚动同时具有竖直轴侧旋。理想水平台面上的纯侧旋不会自行把轨迹拐弯。",
         "observe": "白球沿直线前进；速度归零后仍会原地旋转片刻。",
         "table": table, "physics": default,
         "balls": [Ball("cue",Vec2(.5,.635),Vec2(.35,0),Vec3(0,.35/R,60))]},
    ]

