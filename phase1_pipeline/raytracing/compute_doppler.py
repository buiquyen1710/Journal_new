from __future__ import annotations

import math
from typing import Iterable, Tuple

from phase1_pipeline.common import dot, normalize, wavelength_m


def unit_vector_from_angles(theta_rad: float, phi_rad: float) -> Tuple[float, float, float]:
    sin_theta = math.sin(theta_rad)
    return (
        sin_theta * math.cos(phi_rad),
        sin_theta * math.sin(phi_rad),
        math.cos(theta_rad),
    )


def angles_from_vector(vector: Iterable[float]) -> Tuple[float, float]:
    vx, vy, vz = normalize(vector)
    theta = math.acos(max(-1.0, min(1.0, vz)))
    phi = math.atan2(vy, vx)
    return theta, phi


def compute_doppler_hz(
    frequency_hz: float,
    velocity_m_s: Iterable[float],
    propagation_direction_to_receiver: Iterable[float],
) -> float:
    unit_direction = normalize(propagation_direction_to_receiver)
    return dot(velocity_m_s, unit_direction) / wavelength_m(frequency_hz)
