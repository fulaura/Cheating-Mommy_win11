#!/usr/bin/env python3
from __future__ import annotations

import random
import time
from pynput import mouse


_MOUSE = mouse.Controller()


def get_cursor_pos() -> tuple[int, int]:
    """Return current cursor position in screen coordinates (Windows)."""
    x, y = _MOUSE.position
    return (int(x), int(y))


def move_cursor_smooth(
    *,
    x: int,
    y: int,
    duration: float = 0.10,
    steps: int = 12,
    speed: float = 0.0,
    curve_strength: float = 0.0,
    path_mode: str = "direct",
    jitter: float = 0.0,
    debug: bool = False,
) -> None:
    """Move cursor smoothly to (x,y) using pynput on Windows."""
    steps = max(int(steps), 1)
    duration = max(float(duration), 0.0)
    per_step_sleep = (duration / steps) if steps > 0 else 0.0

    start_x, start_y = get_cursor_pos()
    dx = int(x) - start_x
    dy = int(y) - start_y
    distance = (dx * dx + dy * dy) ** 0.5
    if speed and speed > 0:
        duration = distance / float(speed)
        per_step_sleep = (duration / steps) if steps > 0 else 0.0
    if debug:
        print(
            f"move: start=({start_x},{start_y}) target=({x},{y}) steps={steps} duration={duration}",
            flush=True,
        )

    def ease(t: float) -> float:
        # Smoothstep: 3t^2 - 2t^3
        return t * t * (3.0 - 2.0 * t)

    mid_x = start_x + dx * 0.5
    mid_y = start_y + dy * 0.5
    if distance > 0:
        perp_x = -dy / distance
        perp_y = dx / distance
    else:
        perp_x = 0.0
        perp_y = 0.0
    if str(path_mode).lower() == "indirect":
        ctrl_x = mid_x + (perp_x * float(curve_strength))
        ctrl_y = mid_y + (perp_y * float(curve_strength))
    else:
        ctrl_x = mid_x
        ctrl_y = mid_y

    jitter = max(float(jitter), 0.0)
    for i in range(1, steps + 1):
        t = i / steps
        k = ease(t)
        inv = 1.0 - k
        step_x = int(round((inv * inv * start_x) + (2 * inv * k * ctrl_x) + (k * k * x)))
        step_y = int(round((inv * inv * start_y) + (2 * inv * k * ctrl_y) + (k * k * y)))
        if jitter and i != steps:
            step_x += int(round(random.uniform(-jitter, jitter)))
            step_y += int(round(random.uniform(-jitter, jitter)))
        _MOUSE.position = (step_x, step_y)
        if per_step_sleep:
            time.sleep(per_step_sleep)

    if debug:
        end_x, end_y = get_cursor_pos()
        print(f"move: end=({end_x},{end_y})", flush=True)
