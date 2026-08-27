# metrolink-scheduling

How few trainsets does it take to operate a full weekday of Metrolink service?

This repository answers that from the published GTFS feed. The pipeline picks a
*typical Monday* — Oct 19, 2026, chosen because the services scheduled that day
are identical before and after the feed's exceptions are applied — carrying **132
trips** across the seven lines. The Redlands **Arrow** trips are excluded: Arrow
runs FLIRT DMUs maintained only at the Arrow Maintenance Facility, a separate
fleet that cannot chain with locomotive-hauled equipment, but the feed files them
under the San Bernardino Line with nothing to mark them apart.
`data_collection.py` drops them by `trip_short_name` (38xx), removing 46 of the
day's 178 trips. That exclusion is what lowers the answer: with the DMU trips in,
the same model returned 38 trainsets and a longest block of 11 trips. They were
not making the problem harder so much as making it fictitious.

Each trip is reduced to four facts — departure station, arrival station, and the
two clock times in seconds past midnight — and two trips chain when one set can
run both. Four scenarios vary what that permits: a same-station turn only; an
empty repositioning move as well, penalised; the same unpenalised, as a control;
and finally the requirement that every set start and finish the day at its own
overnight depot.

**The answer is 35 trainsets with same-station turns only, 31 once deadheading is
allowed, and still 31 with home depots enforced.** Metrolink's own floor for a
normal weekday was
[**36**](https://www.trains.com/trn/news-reviews/news-wire/locomotive-issues-lead-to-metrolink-train-cancellations/),
so 35 sits just under a real operator's number rather than implausibly below it.

## Modelling assumptions

Every number here is a **lower bound on equipment need, not an operating plan**.
The assumptions all point the same way — they make chaining easier than it is —
so the true requirement is higher than what comes out.

1) **The day.** One weekday. Saturday and Sunday carry 60 non-Arrow trips each and
  are never evaluated: `services_active_on` indexes `calendar.txt` by a
  five-element weekday list, and the 14 dates in `calendar_dates.txt` that change
  service are not examined. A real fleet is sized for the busiest day of the year.
2) **The equipment.** Every set is interchangeable; consist size, capacity and load
  are out of scope, so a set is never too short for its trip. Excluding Arrow at
  least makes all blocks single-mode.
3) **The chaining rule.** `TURNAROUND` = 20 min is a *lower* bound on the physical
  turn, not a schedule. Nothing distinguishes a 20-minute turn from a 10-hour one,
  or charges for the platform the long one occupies.
4) **Deadhead times.** Shortest path over mean consecutive-stop *revenue* running
  times, restricted to stations served that Monday. Optimistic three ways: a light
  move is timed as a stopping revenue train; there is no dispatcher, track warrant
  or freight on the BNSF and UP trackage; and track the schedule does not use
  cannot be represented at all.
5) **Costs.** `TRAINSET_DAYS_PER_DEADHEAD_HOUR` = 0.17 prices a deadhead train-hour
  (~$665) against a trainset-day (~$4,030), derived in
  [trainset_value_hours_estimation.md](trainset_value_hours_estimation.md).
  Raising it, or `TURNAROUND`, can only discourage chaining, so the fleet count
  moves monotonically with both.
6) **Why only deadheads are penalised.** A deadhead is a non-revenue train movement
  and expends fuel, crew and track time to earn nothing, so it is charged for.
  A same-station chain requires no such movement — the set simply changes ends
  where it already stands — and so carries no penalty in any of the four models.
  That is worth revisiting: a set idling at a platform still incurs real costs
  (servicing, layover crew, the track it occupies) and an opportunity cost, so a
  long same-station layover is not as free as a weight of 1 implies.
7) **Depots.** Only scenario 4 has any, and it knows two — the
  [CMF](https://metrolinktrains.com/community-main/cmf/) at LAUS (capacity 30) and
  the Eastern Maintenance Facility at San Bernardino (7) — where Metrolink also
  stables at Lancaster, East Ventura, Moorpark, Riverside, Perris Valley and
  Stuart Mesa. The missing facilities are the largest source of error in that
  model's positioning cost, and `OVERNIGHT_DEPOTS` still carries a `MUST ADD MORE!!!!`.
8) **Never checked.** No block duration cap, no time feasibility test on depot
  moves, no crew roster, no maintenance window, no yard track count.
  [block_length_upper_bound.md](block_length_upper_bound.md) works out the ceiling
  that *would* apply: no federal rule limits a block's length directly, but 49 CFR
  238.303, 238.305 and 229.21 require a daily inspection at a qualified facility,
  capping the depot-to-depot cycle near 20 hours.
9) **The solver.** The three zero-depot variants are minimum path covers. Their
  constraint matrix has exactly two ones per column, so it is totally unimodular
  and the *continuous* relaxation is integral anyway — which is why
  `min_path_cover.py` does not ask CBC for integers. Scenario 4 is not a path
  cover and declares binary variables.

## Fleet reports

Four scenarios in increasing order of realism, each one arc set plus one
objective. Captured report output lives in
[src/analysis/reports/](src/analysis/reports/), so the numbers below can be
checked without running anything.

| | Chainings | Fleet | Empty running | Sets out of position |
| --- | --- | --- | --- | --- |
| [1. `zero_depot`](#1-zero_depot--no-deadheading) | 2,115 | **35** | none | 0 |
| [2. `zero_depot_deadheading`](#2-zero_depot_deadheading--deadheading-penalised) | 5,316 | **31** | 6:08:53 over 5 moves | 4 |
| [3. `..._UNWEIGHTED`](#3-zero_depot_deadheading_unweighted--the-control) | 5,316 | **31** | 61:16:42 over 39 moves | 4 |
| [4. `multi_depot`](#4-multi_depot--every-set-home-overnight) | 5,316 × 2 depots | **31** = 24 + 7 | 8:34:08 in block, 70:04:10 to depots | 0 by construction |

### 1. `zero_depot` — no deadheading

A set picks up its next trip only where it last stopped, giving **2,115 valid
chainings** over all 132² ordered pairs. Every arc moves strictly forward in time,
so the graph is a DAG and the minimum fleet is its minimum path cover.
[Report](src/analysis/reports/zero_depot.md).

**35 blocks** · 2–7 trips (mean 3.77, stdev 1.24) · spans 3:43–18:18 (median
13:18) · 97 turns, all same-station · revenue 225 of 445 block-hours = **51%**.

- **The day balances.** The multiset of origins exactly equals the multiset of
  termini at all eleven stations involved — 10 blocks start and end at San
  Bernardino, 6 and 6 at LAUS, and so on. Nothing needs repositioning overnight
  for the schedule to repeat, and nothing in the model asked for it.
- **Most endpoints are real stabling points** — both ends of 30 of the 35 blocks.
  The other five begin or end at Chatsworth, Vista Canyon or Redlands - Downtown,
  none a documented storage location, so those sets need a deadhead this model
  cannot price.
- **The long blocks are the questionable ones.** 51% revenue share is normal for
  peak-heavy commuter rail and is exactly what buys the low count, but blocks 6,
  14 and 19 span 16 hours or more, and blocks 20, 29 and 34 all end at Lancaster —
  a storage track with no fueling, so a servicing window there is not one at all.

### 2. `zero_depot_deadheading` — deadheading, penalised

Allowing an empty repositioning move triples the arc set to **5,316**: a chaining
is legal when the gap covers a turnaround, the empty move, and another turnaround.
Each arc is worth one trainset saved *less* the cost of the empty run, making the
objective `(chainings) − (deadhead hours) × 0.17`.
[Report](src/analysis/reports/zero_depot_deadheading.md).

| | No deadheading | Penalised |
| --- | --- | --- |
| Blocks | 35 | **31** |
| Trips per block | 2–7, mean 3.77, stdev 1.24 | 2–7, mean 4.26, stdev 1.06 |
| Tukey outliers | none | blocks 8 (7 trips), 29 (2 trips) |
| Span | 3:43–18:18, median 13:18 | 3:53–18:18, median 13:33 |
| Turns | 97 same-station | 96 same-station + **5 deadheads** |
| Empty running | none | **6:08:53** |
| Revenue share | 225 / 445 h = 51% | 225 / 422 h = 53% |

- **Pricing the move is what makes the answer well-defined** — leave every arc
  worth 1 and *any* maximum matching is optimal (scenario 3). The rate's
  reciprocal is the break-even deadhead, about 6 h; the worst arc available is
  4.32 h, so the penalty only *orders* equally-good solutions rather than
  forbidding any. Fleet size is insensitive across ~1e-7 to 0.37 — far wider than
  the cost estimate's uncertainty — and what holds the model inside that band is
  `assert fleet_size == 31`, not the rate.
- **The empty mileage is small; the margins are not.** 6.15 h total, ~1.5 h per
  trainset saved, but each move absorbs a turnaround at both ends:

  | Empty | Gap | Slack | Move |
  | --- | --- | --- | --- |
  | 1.45 h | 2.60 h | 29 min | Riverside → LAUS |
  | 1.36 h | 2.35 h | 19 min | Riverside → Laguna Niguel / Mission Viejo |
  | 1.31 h | 2.02 h | **2 min** | Laguna Niguel / Mission Viejo → LAUS |
  | 1.18 h | 2.82 h | 58 min | Vista Canyon → LAUS |
  | 0.84 h | 2.30 h | 47 min | Chatsworth → LAUS |

  Two minutes in hand is a schedule, not a plan.
- **It relocates the imbalance rather than removing it.** Four of the five
  deadheads run into Union Station, repositioning *into* a maintenance opportunity
  and collecting Chatsworth and Vista Canyon on the way — but only as *termini*:
  both still originate a block and neither now receives one. Where scenario 1
  balanced everywhere, LAUS now ends with 6 blocks terminating against 2
  originating. **Four sets finish out of position, exactly as many as the model
  saved**, and putting them back is four more overnight moves the objective never
  sees.
- **The blocks tighten in the middle, not at the edges.** The IQR halves while the
  range holds: longest still 7 trips, shortest still 2. As the fences close from
  [0, 8] to [2.5, 6.5], deadheading *creates* two Tukey outliers where there were
  none.

So 31 is the right answer to the question as posed and the wrong number to plan
against.

### 3. `zero_depot_deadheading_UNWEIGHTED` — the control

The same 5,316 arcs, every one worth exactly 1. This exists to answer one
question: **is 31 an artifact of the weighting?** It is not.
[Report](src/analysis/reports/zero_depot_deadheading_unweighted.md).

| | Penalised | Unpenalised |
| --- | --- | --- |
| Blocks | 31 | **31** |
| Deadheads | 5 | **39** of 101 turns |
| Empty running | 6:08:53 (mean 74 min) | **61:16:42** (mean 94 min) |
| Longest single move | 1.45 h | **2.81 h** (Lancaster → Moorpark) |
| Span | 3:53–18:18, median 13:33 | 10:45–18:31, median 14:02 |

- **Ten times the empty running for the same fleet.** With unit weights the
  objective cannot distinguish a same-station turn from a two-hour light move
  across the network, so it does not try. This is the whole case for weighting.
  Both solutions are optimal for their own objective; only one is operable.
- **Read its block statistics with suspicion.** They look *better* than the
  penalised fleet's — 3–6 trips, stdev 0.73, no outliers — but the optimum is not
  unique. CBC returns one maximum matching of many, so the distribution reflects
  which one it found rather than anything about the schedule. Removing that
  non-uniqueness is precisely what the penalty does.

### 4. `multi_depot` — every set home overnight

Every trainset is now drawn from an overnight depot in the morning and must be
back at **the same one** at night, which turns the matching into a **max-cost
flow** problem. Each chaining arc is duplicated per depot, so a variable says
*which depot's set* runs this chain; degree constraints still give every trip one
arc in and one out; per-depot flow conservation forces a single depot label to
propagate along a whole chain; and depot capacity caps what a facility may send
out. Depot legs carry the same rate without the `+ 1` — positioning an empty set
saves no trainset, so it is pure cost.
[Report](src/analysis/reports/multi_depot.md).

| | Penalised, no depots | Multi-depot |
| --- | --- | --- |
| Blocks | 31 | **31** = 24 LAUS + 7 San Bernardino |
| Trips per block | 2–7, stdev 1.06 | 3–6, stdev **0.82** |
| Tukey outliers | blocks 8 and 29 | **none** |
| Span | 3:53–18:18, median 13:33 | 10:17–17:27, median 14:06 |
| In-block empty running | 5 deadheads, 6:08:53 | 6 deadheads, **8:34:08** |
| Depot positioning | not modelled | **70:04:10** over 40 legs |

- **The fleet does not grow**, so a home depot costs nothing in trainsets. But San
  Bernardino finishes at **7 of 7**, so its capacity binds, and the split is only
  as good as a two-facility depot list.
- **It tightens the blocks at both ends.** The 7-trip outlier and the 2-trip stub
  both vanish, and the shortest span jumps from 3:53 to 10:17 — a set that must be
  fetched from and returned to a depot is not worth sending out for a three-hour
  duty. San Bernardino's seven are the longer duties (mean 4.71) against LAUS's
  4.12; `figures/block_lengths_multi_depot.png` bands the two side by side.
- **The cost lands where the earlier models could not see it.** In-block empty
  running rises only from 6.15 to 8.57 h, but the depot legs add **70:04:10** —
  eight times that, ~2.26 h per set per day, with only 22 of the 62 legs free.
  Much of that is the short depot list rather than the schedule: with only LAUS
  and San Bernardino available, a set finishing at Lancaster, Perris, Ventura or
  Oceanside faces a two-hour run home, where Metrolink in fact stables at all four.
- **This is the trade the earlier scenarios hid.** Scenario 2 left four sets out
  of position and never paid; scenario 4 pays explicitly, and the bill is 70
  hours. The endpoint balance still reports two blocks finishing away from where
  they started, but that is measured at *revenue* endpoints and is now cosmetic —
  the model balances at the depot.
- **Still unchecked:** depot legs have no time feasibility test, the depot
  deadhead times are the same idealised means, and nothing caps block length. The
  worst set is out **19:50:08** door to door, inside the ~20 h ceiling by ten
  minutes.

## Layout

```
metrolink/
├── gtfs_raw/                     Metrolink GTFS feed, exactly as published
├── gtfs_cleaned/                 Working copy, plus typical_monday.txt — the 132 trips
├── src/
│   ├── data_processing/          Builds the typical-Monday dataset the models run on
│   │   ├── data_collection.py      calendar.txt + calendar_dates.txt -> services active on a
│   │   │                           day; drops the Arrow DMU trips; writes the typical Monday
│   │   ├── typical_monday_trips.py Each trip -> (dep stop, arr stop, dep time, arr time)
│   │   └── preformulation.py       valid_pair() and valid_pair_deadheading() — the chaining
│   │                               rules and the arc sets; deadhead times; the weights;
│   │                               OVERNIGHT_DEPOTS and their capacities
│   ├── solvers/                  Each variant is arc set + objective, nothing else
│   │   ├── min_path_cover.py       solve() — variables, constraints, CBC. Shared by the three
│   │   ├── zero_depot.py           Unit weights, no-deadheading arcs (asserts 35)
│   │   ├── zero_depot_deadheading.py            Weighted deadheading arcs (asserts 31)
│   │   ├── zero_depot_deadheading_UNWEIGHTED.py The same arcs unweighted (asserts 31)
│   │   └── multi_depot.py          Max-cost flow, arcs labelled by home depot. Builds its own LP
│   ├── analysis/                 What the solutions mean. One report per solver
│   │   ├── fleet_report.py         Blocks, spans, endpoint balance, utilisation, deadhead
│   │   │                           census, over any blocks_dict — shared by all four
│   │   ├── zero_depot_report.py, zero_depot_deadheading_report.py,
│   │   ├── zero_depot_deadheading_UNWEIGHTED_report.py
│   │   ├── multi_depot_report.py   Blocks partitioned by depot, plus the positioning census
│   │   └── reports/                Each report's captured output, one .md per scenario
│   ├── fleet_min-pulp.sol        CBC's solution to that LP, kept for inspection
│   └── viz/                      Plotting; imports the reports, never re-derives them
│       ├── block_lengths.py        Stats and bar chart over any blocks_dict; `groups` bands it
│       └── zero_depot_viz.py, zero_depot_deadheading_viz.py, multi_depot_viz.py
├── figures/                      Charts written by src/viz/
├── tests/test_valid_pair.py      Boundary cases, exhaustive properties, named real pairs
├── trainset_value_hours_estimation.md   Derivation of TRAINSET_DAYS_PER_DEADHEAD_HOUR
├── block_length_upper_bound.md   How long one set's day may run, and why ~20 h door-to-door
├── requirements.txt, pytest.ini
└── PuLP_solver_files/            Saved MPS export of the LP, for inspection
```

Scripts locate `gtfs_cleaned/` relative to their own file, so reads never depend
on the working directory. `src/` is a package: run each stage as a module from the
repository root. Importing a report solves its LP once, and the solvers are not
run directly.

```
python -m src.data_processing.data_collection       # writes gtfs_cleaned/typical_monday.txt
python -m src.data_processing.typical_monday_trips  # prints the per-trip schedule
python -m src.data_processing.preformulation        # prints the valid arcs

python -m src.analysis.zero_depot_report            # 35 trainsets, no empty running
python -m src.analysis.zero_depot_deadheading_report            # 31, and 6.1 h of it
python -m src.analysis.zero_depot_deadheading_UNWEIGHTED_report # 31, and 61.3 h of it
python -m src.analysis.multi_depot_report           # 31 = 24 + 7, per depot then fleet-wide

python -m src.viz.zero_depot_viz                    # stats + figures/block_lengths.png
python -m src.viz.zero_depot_deadheading_viz        # figures/block_lengths_deadheading.png
python -m src.viz.multi_depot_viz                   # figures/block_lengths_multi_depot.png
pytest                                              # 30 tests
```

## Dependencies

Python 3.13. `python -m venv .venv`, activate it, then
`pip install -r requirements.txt`.

| Package | Used for |
| --- | --- |
| [pandas](https://pandas.pydata.org/) | reading and filtering the GTFS `.txt` tables |
| [PuLP](https://github.com/coin-or/pulp) | modelling the LP and driving the solver |
| [networkx](https://networkx.org/) | shortest-path deadhead times over the station graph |
| [matplotlib](https://matplotlib.org/) | the block-length charts in `figures/` |
| [pytest](https://pytest.org/) | the test suite |

PuLP ships with the [CBC](https://github.com/coin-or/Cbc) solver, so no separate
solver install is needed.

## Credits

- **Schedule data**: [Metrolink](https://metrolinktrains.com/) (Southern
  California Regional Rail Authority) GTFS feed, version 20260505, redistributed
  unmodified in [gtfs_raw/](gtfs_raw/) for reproducibility. It remains the
  property of its publisher and is not covered by this repository's license.
- **pandas** — BSD 3-Clause · **PuLP** — MIT-style, © J.S. Roy and S.A. Mitchell ·
  **COIN-OR CBC** — EPL 2.0, inside the PuLP wheel · **pytest** — MIT.

## License

MIT — see [LICENSE](LICENSE). Applies to the code; the GTFS data in
[gtfs_raw/](gtfs_raw/) and [gtfs_cleaned/](gtfs_cleaned/) belongs to Metrolink.
