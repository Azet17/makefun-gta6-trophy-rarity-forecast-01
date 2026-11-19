[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Azet17/makefun-gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Azet17/makefun-gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

# GTA VI Trophy Rarity Forecast

Entry for make.fun competition `gta6-trophy-rarity-forecast-01`: forecast
each Grand Theft Auto VI (PS5) trophy's Exophase earn rate at
2026-11-26T00:00:00Z as five quantiles (5/25/50/75/95%).

Bounty page: https://make.fun/bounty/gta6-trophy-rarity-forecast-01

Referral code: `3cnb50c1`

## Run

```sh
python3 main.py
```

Reads every `*.in` file in `$MAKEFUN_INPUT_DIR` (else `/input/`) and
writes one `/output/<id>.out` per case (to `$MAKEFUN_OUTPUT_DIR`, else
`/output/`).

## Program

`main.py` — Python 3.13, standard library only, no network, deterministic.

It reads every `*.in` file in `$MAKEFUN_INPUT_DIR` (else `/input/`) and
writes one `/output/<id>.out` per case (to `$MAKEFUN_OUTPUT_DIR`, else
`/output/`).

## Approach

Per trophy, on the logit scale (rates clamped to [0.01, 99.99] first):

1. **Trend fit.** Least-squares line of logit(rate) against
   `ln(1 + hours since 2026-11-19T00:00:00Z)` over the last 24 hours of
   reads carrying the trophy (needs >= 3 reads; otherwise the forecast
   is flat at the last rate's median). The line is extrapolated to the
   target, anchored at the last observed logit.
2. **Slope damping.** The extrapolated movement is scaled by
   `1 / (1 + 0.15 * horizon_days)` and capped at 3.0 logit units, so a
   launch-night trend cannot explode over the 4.5-day final horizon.
3. **Spread.** `sigma = sqrt((0.5*sqrt(horizon_days))^2 + resid^2 + shock^2)`
   where `resid` is the fit's residual std floored at 0.15 logit units
   and `shock` is a refresh term (0.35 always, plus up to 0.55 graded by
   how flat the history is: a residual std of 0 means fully flat, 0.10
   or more means genuinely moving). Exophase refreshes its counts in jumps — the practice cases
   prove a flat launch-night page can move every rate at once at the
   first refresh — so a flat history is treated as a stale page, not a
   stable rate, and gets a wider band.
4. **Quantiles.** `z = [-1.645, -0.674, 0, 0.674, 1.645]` on the logit
   scale, mapped back to percent, clamped to [0.01, 99.99] and forced
   non-decreasing.

## Edge cases handled

- `null` rates in some reads and trophies absent from early reads:
  those reads are skipped for that trophy.
- Rates of 0% or 100% (e.g. the 100% trophy): clamped before the logit.
- Single-read history: flat forecast at the last rate.
- The platinum trophy (id 1, 0.63% at launch): forecast like any other
  trophy; its low rate is handled by the logit scale, which is also the
  scoring scale.

## Testing

```sh
KIT=/home/hatch/workspace/makefun-tooling/gta6-trophy-rarity-forecast-01-kit/gta6-trophy-rarity-forecast-01-kit
MAKEFUN_INPUT_DIR=$KIT/input MAKEFUN_OUTPUT_DIR=/tmp/gta6trophy-out python3 main.py
```

Validated on the kit practice cases (p00, p01): each output parses, has
exactly 55 rows with ids matching the case trophies, monotone quantiles
in range, and two runs produce byte-identical output.
