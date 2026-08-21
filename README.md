# metrolink-scheduling

How few trainsets does it take to operate a full weekday of Metrolink service?

This repository answers that question for the Southern California Metrolink
network from its published GTFS feed. The pipeline picks a *typical Monday* out
of the feed — Oct 19, 2026, chosen because the set of services scheduled that
day is identical before and after applying the feed's service exceptions, so it
represents ordinary operation rather than a holiday or a special event. That day
carries **132 trips** across the seven Metrolink lines.

The Redlands **Arrow** trips are excluded. Arrow runs FLIRT DMUs maintained
exclusively at the Arrow Maintenance Facility in San Bernardino, so they are a
separate fleet that cannot chain with locomotive-hauled equipment — but the feed
files them under the San Bernardino Line rather than a route of their own, so
nothing in the GTFS tables marks them apart. `data_collection.py` drops them by
`trip_short_name`, which Arrow numbers 38xx, removing 46 of the day's 178 trips.

Each trip is reduced to the only four facts that matter for equipment planning:
the station it departs from, the station it arrives at, and the two clock times,
in seconds past midnight. Two trips can be run back-to-back by the same trainset
when the first *ends* where the second *begins* and at least 20 minutes separate
the arrival from the following departure — enough to change ends and service the
set. The turnaround is a **lower** bound only: a set laying over at Lancaster
from morning until evening is a legal, if idle, chain, and on the outer ends of
the AV and VC lines a necessary one. Applying that rule to all 132² ordered
pairs yields **2,115 valid chainings**.

Treat trips as nodes and valid chainings as directed arcs and the result is a
DAG — every arc moves strictly forward in time, so no sequence of chains can
close a loop. The minimum number of trainsets is then the **minimum path cover**
of that DAG, which is the trip count minus the size of a maximum matching in the
associated bipartite graph. The matching is solved as a linear program in PuLP,
maximizing the arcs used subject to at most one arc entering and at most one
leaving each trip. The LP uses *continuous* variables rather than binary ones on
purpose — the constraint matrix has exactly two ones per column, one in the
"departing" block and one in the "arriving" block, making it totally unimodular,
so the relaxation lands on an integral optimum anyway and CBC gets an easier
problem.

The answer, for a typical Monday under a 20-minute turnaround and no
deadheading, is **35 trainsets** for 132 trips; allowing deadheading it falls to
**31**. Metrolink's own floor for a normal weekday was
[**36**](https://www.trains.com/trn/news-reviews/news-wire/locomotive-issues-lead-to-metrolink-train-cancellations/),
so 35 sits just under a real operator's number rather than implausibly below it.
Excluding Arrow is what moved it there: with the DMU trips in, the same model
returned 38 trainsets and a longest block of 11 trips; without them, 35 and 7.
The Arrow trips were not making the problem harder so much as making it
fictitious, chaining into locomotive-hauled work no DMU could cover.

### Modelling assumptions

The count is a lower bound on real equipment needs, not an operating plan.
Consist size, maintenance windows, crew rules, and yard capacity are all out of
scope, and every set is treated as interchangeable. Two constants in
[src/preformulation.py](src/preformulation.py) set how conservative the result
is: `TURNAROUND`, and `TRAINSET_DAYS_PER_DEADHEAD_HOUR` in the deadheading
variant. Raising either can only discourage chaining, never encourage it, so the
fleet count moves monotonically with both — and, as
[Pricing a deadhead](#pricing-a-deadhead) shows, is insensitive to the second
across its whole plausible range.

### Are the 35 blocks operable?

Everything in this section describes the **no-deadheading** fleet — the 35 blocks
`zero_depot.py` solves. `fleet_report.py` prints where each block starts and ends,
its **span** (first departure to last arrival), how the endpoints balance, and
what share of block time is revenue service. Three things stand out.

**The day balances.** The multiset of origins is exactly the multiset of
termini: 10 blocks start at San Bernardino and 10 end there, 6 and 6 at LAUS,
5 and 5 at Riverside, and so on across all eleven stations involved. Nothing
needs repositioning overnight for the schedule to repeat, so 35 sets is a steady
state rather than a one-day trick — and nothing in the model asked for it, it
falls out of the matching.

**Most endpoints are real stabling points.** Metrolink overhauls equipment at
the [Central Maintenance Facility](https://metrolinktrains.com/community-main/cmf/)
beside LAUS and at the Eastern Maintenance Facility in Colton, minutes from San
Bernardino - Downtown, and stables sets overnight at Lancaster, East Ventura,
Moorpark, Riverside, Perris Valley, and Stuart Mesa north of Oceanside — both
ends of 30 of the 35 blocks. The other five begin or end at Chatsworth, Vista
Canyon, or Redlands - Downtown, none a documented storage location, so those
sets need a deadhead the base model cannot price.

**The long blocks are the questionable ones.** Spans run 3:43 to 18:18 (median
13:18), and fleet-wide the sets are in revenue service for 225 of 445
block-hours, or 51%. That idleness is normal for peak-heavy commuter rail and is
exactly what buys the low fleet count. Only three blocks span 16 hours or more —
6, 14, and 19 — and an 18:18 span leaves under six hours before the set is needed
again, against
[49 CFR 238.303](https://www.ecfr.gov/current/title-49/subtitle-B/chapter-II/part-238/subpart-D/section-238.303),
which requires an exterior mechanical inspection every calendar day equipment is
in service. What matters as much as the length is *where* the set sits: blocks
20, 29 and 34 all end at Lancaster, a storage track with no fueling, so a
servicing window there is not a servicing window at all.

One caveat outweighs all of this: none of it leaves the typical weekday. Saturday
and Sunday carry 60 non-Arrow trips each against the weekday 132, which
`services_active_on` in [src/data_collection.py](src/data_collection.py) cannot
even evaluate, since it indexes `calendar.txt` by a five-element weekday list;
the 14 dates in `calendar_dates.txt` that change service are never examined
either. A real fleet is sized for the busiest day, holidays included.

Excluding Arrow does at least make the blocks single-mode: every one of the 35 is
locomotive-hauled throughout, where before, all 46 Arrow trips landed in blocks
that also carried locomotive-hauled work. Redlands survives it, though — trips
309 and 342 are San Bernardino Line runs extended to Redlands - Downtown, so one
block still starts there and one ends there.

### Pricing a deadhead

Deadheading is repositioning an empty set, and a model that allows it for free
will use it freely. `preformulation.py` prices each empty move against the
trainset it saves: a deadhead train-hour (~$665 — fuel at 3.00 gal/train-mile,
plus wear and part of the crew's time) over a trainset-day (~$4,030 — a
six-unit consist over an FTA 39-year life, plus crew, servicing and idle fuel).
That ratio is `TRAINSET_DAYS_PER_DEADHEAD_HOUR ≈ 0.17`, making the objective
`(chainings) − (deadhead hours) × 0.17` rather than a bare count of chainings.
The derivation and its sources are in
[trainset_value_hours_estimation.md](trainset_value_hours_estimation.md).

The reciprocal is the break-even deadhead, about 6 hours; nothing here is that
long, the worst available arc being 4.32 h, so the penalty only *orders*
solutions that chain equally many trips rather than forbidding any — it would
begin forbidding above 0.232. Fleet size is insensitive to the rate across a far
wider band than the cost estimate's uncertainty: anything from ~1e-7 to 0.37
returns the same 31 trainsets over the same five deadheads, and what keeps the
model inside that band is `assert(fleet_size == 31)`, not the rate.

### What deadheading buys

Dropping the requirement that a set pick up its next trip where it last stopped
triples the arc set, from **2,115 chainings to 5,316**, and the fleet falls from
**35 to 31** — four trainsets, 11%. A chaining is legal when the gap covers a
turnaround, the empty move, and another turnaround, over a graph containing only
the stations served that Monday.

**The empty mileage is small; the margins are not.** The solution uses 101 turns,
of which **96 are ordinary same-station turns and 5 are deadheads**, totalling
**6.15 hours** of empty running — about 1.5 h per trainset saved. But each move
absorbs a turnaround at both ends, and the remainder is thinner than the raw gap:

| Empty | Gap | Slack | Move |
| --- | --- | --- | --- |
| 1.45 h | 2.60 h | 29 min | Riverside - Downtown → L.A. Union Station |
| 1.36 h | 2.35 h | 19 min | Riverside - Downtown → Laguna Niguel / Mission Viejo |
| 1.31 h | 2.02 h | **2 min** | Laguna Niguel / Mission Viejo → L.A. Union Station |
| 1.18 h | 2.82 h | 58 min | Vista Canyon → L.A. Union Station |
| 0.84 h | 2.30 h | 47 min | Chatsworth → L.A. Union Station |

Two minutes in hand is a schedule, not a plan. A light move over BNSF and UP
trackage gets no such guarantee, and the model has no dispatcher, no track
warrant, and no crew whose shift has to absorb it — the deadhead times are mean
revenue running times over stations the schedule already serves, idealised in
the optimistic direction.

**It relocates the imbalance rather than removing it.** Four of the five deadheads
run into Union Station, where the CMF is — the model repositions *into* a
maintenance opportunity rather than past one, collecting Chatsworth and Vista
Canyon, two of the base model's unstabled endpoints, on the way. But it removes
them only as *termini*: both still originate a block and neither now receives
one, so a set has to reach them overnight regardless, where the base model had
both balanced. The same asymmetry shows up fleet-wide. Under the base model the
multiset of block origins equalled the multiset of termini at every station; with
deadheading, LAUS ends the day with **6 blocks terminating against 2
originating**, Riverside is short 2, and Chatsworth and Vista Canyon 1 each. Four
sets finish out of position — exactly as many as the model saved — and putting
them back is four more overnight moves the objective never sees. The LP maximises
chainings inside one day, so it spends tomorrow's position to buy today's match.

**The blocks get tighter in the middle, not at the edges.**

| | No deadheading | Deadheading |
| --- | --- | --- |
| Blocks | 35 | 31 |
| Trips per block | 2 – 7 | 2 – 7 |
| Mean / median | 3.77 / 4.0 | 4.26 / 4.0 |
| Stdev | 1.24 | 1.06 |
| IQR (Q1–Q3) | 2.0 (3–5) | 1.0 (4–5) |
| Tukey outliers | none | blocks 8 (7 trips), 29 (2 trips) |
| Span | 3:43 – 18:18 (median 13:18) | 3:53 – 18:18 (median 13:33) |
| Revenue share of block-hours | 225 / 445 h = 51% | 225 / 422 h = 53% |

The interquartile range halves, but the range does not move: the longest block is
still 7 trips, the shortest still 2, and the stub duty survives as block 29, a
2-trip 3h53m Chatsworth turn. Since the fences close from [0, 8] to [2.5, 6.5],
deadheading *creates* two Tukey outliers where the base model had none — it
compresses the bulk and leaves both tails in place. Utilisation barely moves
either: revenue hours are fixed at 225, so spreading them over 31 sets rather
than 35 lifts the revenue share of block time only from 51% to 53%.

So 31 is the right answer to the question as posed and the wrong number to plan
against. Metrolink's own weekday floor was 36. The four sets are bought with four
sets left out of position, one empty move with two minutes of slack, and a cost
model that stops at mean running times. Pricing the empty running is what makes
those five deadheads well-defined at all — leave every arc worth 1 and *any*
maximum matching is optimal — but well-defined is not the same as achievable.

## Layout

```
metrolink/
├── gtfs_raw/                     Metrolink GTFS feed, exactly as published
├── gtfs_cleaned/                 Working copy of the feed, plus derived data
│   └── typical_monday.txt          The 132 non-Arrow trips active on Oct 19, 2026
│                                    (written by data_collection.py)
├── src/
│   ├── data_collection.py        Resolves calendar.txt + calendar_dates.txt into the
│   │                             services active on a given day; drops the Arrow DMU trips
│   │                             (trip_short_name 38xx) and writes the typical Monday
│   ├── typical_monday_trips.py   Reduces each typical-Monday trip to
│   │                             (departure stop, arrival stop, departure time, arrival time)
│   ├── preformulation.py         valid_pair() — the chaining rule; builds the arc set of the DAG.
│   │                             Also valid_pair_deadheading(), which prices an empty move as the
│   │                             shortest path over mean station-to-station running times, and
│   │                             TRAINSET_DAYS_PER_DEADHEAD_HOUR, which turns those times into the
│   │                             arc weights exported as weights_and_arcs
│   ├── zero_depot.py             Builds and solves the min-path-cover LP; reports the fleet
│   │                             size, the blocks, and their origins/termini/spans
│   ├── zero_depot_deadheading.py The same constraints over the deadheading arc set, but a
│   │                             weighted objective that charges for empty running (asserts 31)
│   ├── fleet_report.py           Block spans, endpoint balance, utilisation, and the deadhead
│   │                             census, over any blocks_dict — shared by both variants
│   ├── fleet_min-pulp.sol        CBC's solution to that LP, kept for inspection
│   ├── conftest.py               Puts src/ on sys.path for the test suite
│   └── viz/                      Plotting; imports the models, never re-derives them
│       ├── block_lengths.py        Block-length statistics and bar chart, over any
│       │                           blocks_dict — shared by both variants below
│       ├── zero_depot_viz.py       Applies them to the zero-depot fleet
│       └── zero_depot_deadheading_viz.py  ... and to the deadheading fleet
├── figures/                      Charts written by src/viz/
├── tests/
│   └── test_valid_pair.py        Synthetic boundary cases, exhaustive properties over the real
│                                 schedule, and named real-world pairs
├── trainset_value_hours_estimation.md   Derivation of TRAINSET_DAYS_PER_DEADHEAD_HOUR
├── requirements.txt              Pinned dependencies
├── pytest.ini                    Points pytest at tests/ and puts src/ on sys.path
└── PuLP_solver_files/            Saved MPS export of the LP, for inspection
```

The scripts locate `gtfs_cleaned/` relative to their own file, not the working
directory, so they can be run from anywhere. Run the stages in order; each one
is a plain script.

```
python src/data_collection.py      # writes gtfs_cleaned/typical_monday.txt
python src/typical_monday_trips.py # prints the per-trip schedule
python src/preformulation.py       # prints the valid arcs
python src/zero_depot.py           # solves the LP (asserts the fleet size is 35)
python src/viz/zero_depot_viz.py   # block-length stats + figures/block_lengths.png
python src/zero_depot_deadheading.py          # the weighted LP (asserts 31)
python src/viz/zero_depot_deadheading_viz.py  # figures/block_lengths_deadheading.png
python src/fleet_report.py         # spans, balance, utilisation, deadhead census, both variants
pytest                             # 30 tests
```

## Dependencies

Python 3.13. Install with:

```
python -m venv .venv
.venv\Scripts\activate         # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

| Package | Used for |
| --- | --- |
| [pandas](https://pandas.pydata.org/) | reading and filtering the GTFS `.txt` tables |
| [PuLP](https://github.com/coin-or/pulp) | modelling the LP and driving the solver |
| [networkx](https://networkx.org/) | shortest-path deadhead times over the station graph |
| [matplotlib](https://matplotlib.org/) | the block-length charts in `figures/` |
| [pytest](https://pytest.org/) | the test suite |

PuLP ships with the [CBC](https://github.com/coin-or/Cbc) solver that actually
runs the LP, so no separate solver install is needed.

## Credits

- **Schedule data**: [Metrolink](https://metrolinktrains.com/) (Southern
  California Regional Rail Authority) GTFS feed, version 20260505. The feed is
  redistributed here unmodified in [gtfs_raw/](gtfs_raw/) for reproducibility;
  it remains the property of its publisher and is not covered by this
  repository's license.
- **pandas** — BSD 3-Clause, © the pandas development team.
- **PuLP** — BSD-2-Clause-ish MIT-style license, © J.S. Roy and S.A. Mitchell.
- **COIN-OR CBC** — Eclipse Public License 2.0, distributed inside the PuLP wheel.
- **pytest** — MIT, © Holger Krekel and contributors.

## License

MIT — see [LICENSE](LICENSE). Applies to the code in this repository; the GTFS
data in [gtfs_raw/](gtfs_raw/) and [gtfs_cleaned/](gtfs_cleaned/) belongs to
Metrolink.
