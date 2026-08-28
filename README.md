### metrolink-scheduling

How many trainsets does it take to run a full weekday of Metrolink service?

The schedule is fixed — 132 heavy-rail trips — but the *fleet* is not. A trainset that
finishes a trip can pick up another one, so the question is how few sets can cover all 132
trips between them. This repo builds that as a linear program over the Metrolink GTFS feed
and solves it under four sets of operating assumptions, from 35 trainsets down to 31.

**The service day is Monday, October 19, 2026**, chosen because it is exception-free in the
GTFS `calendar_dates` table: the services running that day are exactly the services scheduled
to run, with nothing added or cancelled. It is therefore a *typical* weekday rather than a
particular one.

**Arrow FLIRT DMUs are excluded.** They are a separate technology from Metrolink's heavy rail,
run only on the San Bernardino line, and are maintained exclusively at the Arrow Maintenance
Facility, so they share no equipment with the fleet being sized. Removing them takes the day
from 178 trips to the **132** modelled here; the 46 Arrow trips are identified by
`trip_short_name` in the 38xx range.

## Layout

The pipeline runs left to right: GTFS tables in, arc set, solvers, reports.

```
gtfs_raw/                     Metrolink's published GTFS feed, untouched
gtfs_cleaned/                 the subset this repo reads
  typical_monday.txt            generated - the 132 trips of the service day
src/
  data_processing/
    data_collection.py          picks the exception-free day out of the feed
    typical_monday_trips.py     each trip as (origin, terminus, depart, arrive)
    preformulation.py           which chainings are legal, and what each is worth
  solvers/
    min_path_cover.py           the two-stage LP, shared by both zero-depot variants
    zero_depot.py               no deadheading                          -> 35
    zero_depot_deadheading.py   deadheading, penalised and unpenalised   -> 31
    multi_depot.py              every set home overnight, as max-cost flow -> 31
  analysis/
    markdown_report.py          assembles a report and writes its .md
    fleet/                      given a solved fleet, describe it
      fleet_report.py             blocks, spans, endpoint balance, deadhead census
      *_report.py                 one per scenario
    forcing/                    re-solve under forced variables, and describe that
      forcing_sweep.py            produces the sweep CSVs
      sweep_report.py             reads them back
    reports/                    OUTPUT ONLY - no code here
      fleet_reports/*.md          one per scenario
      sweeps/*.csv                one row per forced re-solve
      sweeps.md                   what the sweep found
  viz/                          block-length figures -> figures/
tests/                          valid_pair, chaining, and the generated-data guard
trainset_value_hours_estimation.md   where the deadhead penalty comes from
```

Two conventions worth knowing. **Code and output never mix**: everything under
`analysis/reports/` is generated, and every `.md` there names the command that regenerates it.
And **the solvers solve at import** — importing `multi_depot` runs both stages — so the module
holds its results as `fleet_size`, `arcs` and friends, which is what the reports and figures
read.

## Modelling assumptions

The fleet is minimised by having each trainset run **several trips in a day**. Two trips run
in succession by one set are a *chain*; the whole day's sequence for one set is a *block*.
Fewer sets means longer blocks, so minimising the fleet is the same problem as chaining as
many trips together as possible.

For chaining purposes a trip is reduced to **four numbers**: origin stop, origin time,
terminus stop, terminus time. Everything else is ignored — notably track availability and
storage capacity at trip endpoints, and the regulatory requirement that sets return to a
maintenance facility such as CMF near L.A. Union Station for daily servicing *(source needed)*.
Only the multi-depot scenario reintroduces the depot constraint.

Two trips **A → B** can be chained when either:

- **A ends where B starts**, with enough time between them to turn the set around; or
- **A ends elsewhere**, with enough time to run empty from A's terminus to B's origin,
  bracketed by a turnaround at each end.

Supporting assumptions:

- **Turnaround is 20 minutes** (`TURNAROUND` in
  [preformulation.py](src/data_processing/preformulation.py)). Metrolink runs push-pull
  consists, so a set reverses by moving the crew to the other end rather than running around
  its train.
- **Deadheading is at least as fast as a nonstop trip.** Empty-move times come from a
  shortest path over a graph of stop-to-stop segments, weighted by mean observed times on
  *revenue* trips. A light move is never assumed faster than a train that actually made it.
- **No refuelling or maintenance is modelled.** Maintenance is structural (see above).
  Refuelling appears not to bind: the longest block in the penalised solution spans
  **17:05:00**, of which **9 h 40 min** is revenue running — roughly **1,100 gallons** at the
  113.8 gal/train-hour derived in
  [trainset_value_hours_estimation.md](trainset_value_hours_estimation.md). Confirming that
  fits in one tank needs a sourced F125 fuel capacity, which that document does not yet have.

Two of the four scenarios weight arcs **against** long empty moves. At the rate used no move
is forbidden outright — the weighting only orders solutions. The derivation is in
[trainset_value_hours_estimation.md](trainset_value_hours_estimation.md).

## The two-stage solve

Every scenario is solved in **two stages**, and the split matters enough to state once here.

A single blended objective — maximise *(chainings) − (deadhead hours) × K* — **cannot
guarantee the fleet size it reports.** A solution with one chaining fewer, but enough empty
running saved, scores identically and comes back as a *larger* fleet. The objective silently
trades trainsets for mileage.

So the two questions are asked separately:

1. **Stage 1 — how small can the fleet be?** Maximise the bare chaining count, ignoring
   weights entirely. Each chaining removes exactly one trainset, so this optimum *is* the
   minimum fleet.
2. **Stage 2 — which minimum-fleet day should we run?** Maximise the scenario's own weighted
   objective, subject to an **equality constraint** pinning the chaining count to stage 1's
   answer. Stage 2 chooses *among* minimum-fleet solutions; it cannot buy weight back with a
   trainset.

The equality is exact, not a bound — slack there is precisely what would let stage 2 spend a
trainset. Scenarios with uniform weights skip stage 2, having nothing to choose between.

This is not a formality. It changes the answer: under a single blended objective the reported
fleet moved between 31 and 35 as K varied, while under the two-stage solve **it is 31 for
every K**, because stage 1 never sees K at all. See
[min_path_cover.py](src/solvers/min_path_cover.py) for the full argument, including why stage 1
may relax to a continuous LP and stage 2 may not.

### Stage 2 pins the numbers, not the solution

**Stage 2 does not make the answer unique.** It pins the fleet size and the optimal objective
*value* — and so the total empty running, which the objective is a linear function of — but
many different schedules achieve them, and which one CBC returns is not something this repo
controls.

The sensitivity sweep demonstrates this directly rather than in principle. In the penalised
model the chosen solution uses 101 chainings, yet **1,989 arcs outside it can each be
mandated at no cost to the objective** — each one a witness to a distinct, equally optimal
schedule. Forcing any of them in returns the same 31 trainsets, the same 06:08:53 of empty
running, and the same objective 99.954831, over a **different set of arcs**. The multi-depot
model is looser still: 163 variables used, **3,123** outside them forceable for free.

The practical consequence runs through the whole repo: **totals are reproducible, composition
is not.** Assertions are written against fleet sizes and aggregate deadhead time, never
against specific chainings, because the latter vary with the CBC build. It also means the
sweep's "critical arcs" are the genuinely load-bearing ones — a move whose removal costs a
trainset, as opposed to the thousands that are merely one option among many.

## Scenarios

| Scenario | Fleet | Empty running | Solver |
| --- | --- | --- | --- |
| No deadheading | **35** | none | [zero_depot.py](src/solvers/zero_depot.py) |
| Deadheading, penalised | **31** | 6 h 08 m, 5 moves | [zero_depot_deadheading.py](src/solvers/zero_depot_deadheading.py) |
| Deadheading, unpenalised (control) | **31** | tens of hours | same file |
| Multi-depot | **31** | 6 h 08 m + depot legs | [multi_depot.py](src/solvers/multi_depot.py) |

**No deadheading — 35 trainsets.** A set may only pick up a trip departing from where it last
stopped, giving 2,115 legal chainings. All arcs weigh the same, so stage 1 answers the whole
question and stage 2 is skipped. This is the honest upper bound: the fleet you need if
equipment never moves except in revenue service.

**Deadheading, penalised — 31 trainsets.** Allowing empty moves more than doubles the legal
chainings to 5,316 and saves **four trainsets**. Each arc is worth one trainset saved less the
cost of the empty run it requires. Stage 1 fixes the fleet at 31; stage 2 then finds the
cheapest way to achieve 31, landing on **five deadheads totalling 6 h 08 m**. Four of the five
terminate at L.A. Union Station — the model is deadheading *into* the maintenance facility,
not past it.

**Deadheading, unpenalised — 31 trainsets.** The control, and the reason stage 2 exists. Same
arcs, every weight set to 1, so the model has no preference among minimum-fleet solutions and
stops after stage 1. It still returns 31 — **the fleet size is not an artifact of the
weighting** — but its empty running is whatever CBC happened to land on, anywhere in the
6 h 08 m to 109 h 57 m the minimum-fleet solutions span. That figure is deliberately asserted
as a *range* rather than a value, because it is not reproducible across solver builds. What
the penalty buys is not a smaller fleet but a *specific, defensible* one.

**Multi-depot — 31 trainsets, 24 from L.A. Union Station and 7 from San Bernardino.** The
realistic case: every set must start and end its day at its own overnight depot, subject to
depot capacity. Reformulated as max-cost flow, with separate variables per home depot, which
multiplies the chaining variables by the number of depots. Both stages declare integer
variables here — the total-unimodularity argument that lets stage 1 relax elsewhere does not
survive the flow-conservation rows. That the fleet stays at **31** is the substantive result:
sending every set home overnight costs nothing in equipment, only in positioning mileage.

## Sensitivity: what each decision is worth

Beyond the four solutions, [forcing_sweep.py](src/analysis/forcing/forcing_sweep.py) re-solves
every scenario once per decision variable per value — **47,814 forced re-solves** — mandating
or forbidding one move at a time to see what it costs. Findings are in
[reports/sweeps.md](src/analysis/reports/sweeps.md):

- **No single forcing makes any scenario infeasible.** Every one of the 47,814 solved.
- **When a forcing costs anything, it costs exactly one trainset** — never two.
- **Forbidding is nearly free; mandating is where the cost is.** In the multi-depot model
  *no* single move is load-bearing: any one can be banned and 31 still met. Without
  deadheading, 21 chainings are critical.
- **The objective is far more fragile than the fleet size** — thousands of forcings keep the
  minimum fleet while losing the optimal positioning, which is the planner's real margin.

## Note: PuLP 4.0 will break the solvers

Every decision variable in this repo is built with `pulp.LpVariable.dict`, which PuLP 3.3
deprecates:

> `LpVariable.dict is deprecated; use prob.add_variable_dict(...) for PuLP 4.0 compatibility.`

Four call sites are affected — one in `src/solvers/min_path_cover.py` and three in
`src/solvers/multi_depot.py`, which builds a dict per variable family (chainings, depot
departures, depot arrivals).

**Nothing is broken today, and nothing needs doing urgently.** `pyproject.toml` constrains
`PuLP>=3.3,<4` and `requirements.txt` pins `PuLP==3.3.2`, so 4.0 cannot arrive by accident.
Ordinary solver runs are also silent, because Python suppresses `DeprecationWarning` by
default; the warnings are visible only under `pytest`, which un-hides them.

Porting the four call sites to `prob.add_variable_dict(...)` is the work that has to happen
before that `<4` bound can be lifted. Since the fleet sizes are the results this repo exists
to report, treat the existing `assert fleet_size == 35 / 31 / 31` guards in the solvers as
the acceptance test for that migration: the numbers must not move.
