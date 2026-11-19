#!/usr/bin/env python3
"""GTA VI trophy rarity forecaster (makefun/gta6-trophies-case/v1).

Forecasts each trophy's Exophase earn rate at the case target as five
quantiles (5/25/50/75/95%) on the logit scale.

Method, per trophy:
  * Clamp every observed rate to [0.01, 99.99] and work in logits.
  * Fit a least-squares line of logit(rate) against ln(1 + hours since
    2026-11-19T00:00:00Z) over the last 24h of reads that carry the
    trophy (needs >= 3 reads, else fall back to the flat last rate).
  * Extrapolate the line to the target, anchored at the last observed
    logit, with the slope damped for long horizons so a launch-night
    trend cannot explode over 4.5 days.
  * Spread combines a random-walk term (0.5 * sqrt(horizon_days)) with
    the fit's residual std (floored at 0.15 logit units), plus a refresh
    shock term: Exophase refreshes its counts in jumps, so a flat
    history (zero residual) is evidence of a stale page, not of a
    stable rate, and gets widened further.
  * Quantiles use z = [-1.645, -0.674, 0, 0.674, 1.645] on the logit
    scale, mapped back to percent, clamped to [0.01, 99.99] and forced
    non-decreasing.

Standard library only, no network, fully deterministic.
"""

import json
import math
import os
from datetime import datetime, timezone

EPOCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)
Z = (-1.645, -0.674, 0.0, 0.674, 1.645)
LO, HI = 0.01, 99.99
# Slope damping: extrapolated movement is scaled by 1 / (1 + DAMP * horizon_days).
DAMP = 0.15
# Hard cap on how far the median may move from the last observed rate.
MAX_MOVE = 3.0
# Random-walk coefficient (logit units per sqrt(day)).
RW = 0.5
# Floor on the residual spread, and the extra shock added when the
# history is flat (a stale page can jump at the next refresh). The
# flatness of a history is graded, not binary: a residual std of 0
# means fully flat, 0.10 or more means genuinely moving.
RESID_FLOOR = 0.15
BASE_SHOCK = 0.35
FLAT_SHOCK = 0.55
FLAT_SCALE = 0.10  # residual std at/above this counts as fully moving
WINDOW_HOURS = 24.0


def parse_time(s):
    """ISO 8601 UTC string -> aware datetime (handles trailing Z)."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clamp_rate(r):
    return min(max(float(r), LO), HI)


def logit(pct):
    p = clamp_rate(pct) / 100.0
    return math.log(p / (1.0 - p))


def sigmoid(x):
    if x >= 0:
        return 100.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return 100.0 * e / (1.0 + e)


def hours_since_epoch(t):
    return (t - EPOCH).total_seconds() / 3600.0


def x_of(t):
    """Log-time axis: ln(1 + hours since launch midnight)."""
    return math.log1p(max(hours_since_epoch(t), 0.0))


def least_squares(xs, ys):
    """Return (intercept, slope) of the least-squares line, or None."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return (my - slope * mx, slope)


def forecast_trophy(idx, trophies, history, target, horizon_days):
    """Return the five quantiles (percent) for trophy index idx."""
    # Collect (time, rate) pairs for this trophy, oldest first, skipping
    # reads that lack it (null) or carry a non-finite rate.
    pts = []
    for read in history:
        rates = read.get("rates") or []
        if idx >= len(rates):
            continue
        r = rates[idx]
        if r is None:
            continue
        try:
            r = float(r)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(r):
            continue
        try:
            t = parse_time(read["at"])
        except (KeyError, TypeError, ValueError):
            continue
        pts.append((t, r))
    if not pts:
        # No observation at all: a neutral 1% median with a wide band.
        center, sigma = logit(1.0), 2.0
        return quantiles(center, sigma)

    last_rate = pts[-1][1]
    last_logit = logit(last_rate)

    # Window: only the last 24h of reads, on the log-time axis.
    cutoff = pts[-1][0].timestamp() - WINDOW_HOURS * 3600.0
    win = [(t, r) for (t, r) in pts if t.timestamp() >= cutoff]

    center = last_logit
    resid_std = 0.0
    flatness = 1.0  # 1 = fully flat/stale history, 0 = genuinely moving
    if len(win) >= 3:
        xs = [x_of(t) for (t, _r) in win]
        ys = [logit(r) for (_t, r) in win]
        fit = least_squares(xs, ys)
        if fit is not None:
            intercept, slope = fit
            resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
            resid_std = math.sqrt(sum(e * e for e in resid) / len(resid))
            flatness = max(0.0, 1.0 - resid_std / FLAT_SCALE)
            # Extrapolate the line to the target, anchored at the last
            # observed logit, with the slope damped for long horizons.
            x_t = x_of(target)
            move = (intercept + slope * x_t) - last_logit
            damp = 1.0 / (1.0 + DAMP * horizon_days)
            move = max(-MAX_MOVE, min(MAX_MOVE, damp * move))
            center = last_logit + move
    else:
        # Fewer than 3 windowed reads: flat forecast at the last rate.
        # Use the median of the last few observed logits as the centre
        # so one stray read cannot pull it.
        recent = [logit(r) for (_t, r) in pts[-3:]]
        recent.sort()
        center = recent[len(recent) // 2]
        flatness = 1.0

    # Spread: random walk + residual (floored) + refresh shock.
    rw = RW * math.sqrt(max(horizon_days, 0.0))
    resid = max(resid_std, RESID_FLOOR)
    shock = BASE_SHOCK + FLAT_SHOCK * flatness
    sigma = math.sqrt(rw * rw + resid * resid + shock * shock)
    return quantiles(center, sigma)


def quantiles(center, sigma):
    out = []
    for z in Z:
        q = sigmoid(center + z * sigma)
        q = min(max(q, LO), HI)
        out.append(round(q, 4))
    # Enforce non-decreasing after rounding.
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def forecast_case(case):
    trophies = case["trophies"]
    history = case.get("history") or []
    target = parse_time(case["target"])
    horizon_days = float(case.get("horizon_minutes", 0)) / 1440.0
    rows = []
    for i, trophy in enumerate(trophies):
        rows.append({"id": int(trophy["id"]),
                     "q": forecast_trophy(i, trophies, history,
                                          target, horizon_days)})
    return {"trophies": rows}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input/"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output/"
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(in_dir) if n.endswith(".in"))
    for name in names:
        with open(os.path.join(in_dir, name), "r", encoding="utf-8") as f:
            case = json.load(f)
        result = forecast_case(case)
        out_path = os.path.join(out_dir, name[:-3] + ".out")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, separators=(",", ":"))
            f.write("\n")


if __name__ == "__main__":
    main()
