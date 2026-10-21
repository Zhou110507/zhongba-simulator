"""Geometric pot tolerance, separate from position-play effort.

First-order cue direction tolerance is proportional to pocket angular aperture
times ball diameter*cos(cut)/cue-to-contact distance (Alciatore TP 3.4).
Projected mouth clearance is a conservative aperture proxy, not measured pocket
acceptance or a human success probability; speed/jaws/throw still need physics.
"""
from math import atan2, cos, degrees, log1p, radians


def geometric_tolerance(half_width, alignment, radius, cue_distance, object_distance, cut_degrees):
    projected_half=max(.0005, half_width*max(0., alignment)-radius)
    outgoing_half=atan2(projected_half,max(.01,object_distance))
    aim_half=degrees(outgoing_half*2*radius*max(.02,cos(radians(cut_degrees)))/max(.03,cue_distance))
    difficulty=log1p(.08/max(.001,aim_half))
    return {'aim_half_window_deg':aim_half,'pot_difficulty':difficulty,
            'projected_pocket_half_mm':projected_half*1000,
            'pocket_entry_cosine':alignment}
