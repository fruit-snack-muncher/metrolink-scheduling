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
`trip_short_name`, which Arrow numbers 38xx. That removes 46 of the day's 178
trips.

Each trip is reduced to the only four facts that matter for equipment planning:
the station it departs from, the station it arrives at, and the two clock times,
expressed in seconds past midnight. Two trips can be run back-to-back by the
same trainset when the first *ends* where the second *begins* and there are at
least 20 minutes between the arrival and the following departure — enough to
change ends and service the set. The turnaround is a **lower** bound only: a set
that lays over at Lancaster from morning until evening is a legal, if idle,
chain, and on the outer ends of the AV and VC lines it is a necessary one.
Applying that rule to all 132² ordered pairs yields **2,115 valid chainings**.

Treat trips as nodes and valid chainings as directed arcs and the result is a
DAG — every arc moves strictly forward in time, so no sequence of chains can
close a loop. The minimum number of trainsets is then the **minimum path cover**
of that DAG, which is the trip count minus the size of a maximum matching in the
associated bipartite graph. The matching is solved as a linear program in PuLP:
maximize the number of arcs used, subject to at most one arc entering and at
most one arc leaving each trip. The LP is written with *continuous* variables
rather than binary ones on purpose — the constraint matrix has exactly two ones
per column, one in the "departing" block and one in the "arriving" block, which
makes it totally unimodular, so the relaxation is guaranteed to land on an
integral optimum anyway and CBC gets an easier problem to solve.

The answer, for a typical Monday under a 20-minute turnaround and no
deadheading, is **35 trainsets** for 132 trips. Allowing deadheading, the number
drops to **31 trainsets** for those same trips.

In the non-deadheading case, there is a very slight discrepancy between Metrolink's 
minimum total locomotives to run a normal weekday schedule, which was **36 trainsets**.
(https://www.trains.com/trn/news-reviews/news-wire/locomotive-issues-lead-to-metrolink-train-cancellations/).

Excluding the Arrow trips is what moved that number: with them in, the same
model returned 38 trainsets, and the longest block ran 11 trips. Without them
the fleet drops to 35 and the longest block to 7 — inside the Tukey fences of
[0, 8], so no block now reads as an outlier at all. The Arrow trips were not
making the problem harder so much as making it fictitious; they chained into
locomotive-hauled work that no DMU could ever cover.

### Modelling assumptions

The count is a lower bound on real equipment needs, not an operating plan. In
the base model deadheading (repositioning an empty set) is not modelled, so a
set can only pick up a trip where it last stopped; [the deadheading
variant](#what-deadheading-buys) relaxes exactly that. Consist size, maintenance
windows, crew rules, and yard capacity are all out of scope, and every set is
treated as interchangeable. `TURNAROUND` in
[src/preformulation.py](src/preformulation.py) is the single knob controlling
how conservative the result is; raising it can only remove chaining
opportunities, never create them, so the fleet count moves monotonically with
it.

### Are the blocks operable?

`zero_depot.py` prints where each block starts, where it ends, and its
**span** — first departure to last arrival. Three things stand out.

**The day balances.** The multiset of origins is exactly the multiset of
termini: 10 blocks start at San Bernardino and 10 end there, 6 and 6 at LAUS,
5 and 5 at Riverside, and so on across all eleven stations involved. Nothing
needs repositioning overnight for the schedule to repeat, so 35 sets is a steady
state rather than a one-day trick — and nothing in the model asked for it, it
falls out of the matching. It also means the blocks chain into **rotations**:
three return to their own origin and can simply repeat the next day (blocks 12,
13, and 23, all San Bernardino to San Bernardino, all carrying an odd number of
trips because they are triangles rather than out-and-backs), and the other 32
decompose into cycles — two two-day pairs, both turning at Lancaster, plus one
ten-day and one eighteen-day. The fleet is 7 pools, not 35 independent duties,
though only the short cycles are forced; the long ones are one valid
decomposition among several. Rotation length is a cost in itself: the
eighteen-day loop opens Perris → Chatsworth → Redlands, collecting the stations
that appear exactly once in the schedule and so cannot pair off with anything.

**Most endpoints are real stabling points.** Metrolink overhauls equipment at
the [Central Maintenance Facility](https://metrolinktrains.com/community-main/cmf/)
beside LAUS and at the Eastern Maintenance Facility in Colton, minutes from San
Bernardino - Downtown, and stables sets overnight at Lancaster, East Ventura,
Moorpark, Riverside, Perris Valley, and Stuart Mesa north of Oceanside. That
covers both ends of 30 of the 35 blocks. The other five begin or end at
Chatsworth, Vista Canyon, or Redlands - Downtown — none a documented storage
location — so those sets need a deadhead the model does not price.

**The long blocks are the questionable ones.** Spans run 3:43 to 18:18 (median
13:18), and fleet-wide the sets are in revenue service for 225 of 445
block-hours, or 51%. That idleness is normal for peak-heavy commuter rail and is
exactly what buys the low fleet count. Only three blocks now span 16 hours or
more — 6, 14, and 19 — and what constrains them is the gap to whatever the set
does next in its rotation, not 24 hours minus the span. The four tightest
handoffs:

| Block | Span | Ends at | Next duty | Overnight |
| --- | --- | --- | --- | --- |
| 23 | 15:48 | San Bernardino, 19:29 | itself, 03:41 | 8:12 |
| 20 | 14:57 | Lancaster, 20:51 | blk 6, 05:11 | 8:20 |
| 29 | 14:10 | Lancaster, 21:51 | blk 7, 06:11 | 8:20 |
| 34 | 14:08 | Lancaster, 19:51 | blk 9, 04:11 | 8:20 |

[49 CFR 238.303](https://www.ecfr.gov/current/title-49/subtitle-B/chapter-II/part-238/subpart-D/section-238.303)
requires an exterior mechanical inspection once each calendar day the equipment
is in service, and fueling, cleaning, and brake tests want the same window.
Eight hours is comfortable for that, so the tightest handoff is no longer the
binding one — Block 23 turns at San Bernardino, minutes from EMF Colton, and
8h12m there is routine. What binds instead is *where* the other three sit:
Lancaster is a storage track with no fueling, and three of the four tightest
turns happen on it. A set stabled at Lancaster or Perris is on a multi-day cycle
back to CMF or EMF that a single-day model cannot see, and the ten- and
eighteen-day rotations above are exactly how long that takes.

One caveat outweighs all of this: none of it leaves the typical weekday.
Saturday and Sunday carry 60 non-Arrow trips each against the weekday 132, which
`services_active_on` in [src/data_collection.py](src/data_collection.py) cannot
even evaluate, since it indexes `calendar.txt` by a five-element weekday list;
the 14 dates in `calendar_dates.txt` that change service are likewise never
examined. A real fleet is sized for the busiest day of the week, holidays and
special events included.

Excluding Arrow does at least make the blocks single-mode: every one of the 35
is now locomotive-hauled throughout, where before, all 46 Arrow trips landed in
blocks that also carried locomotive-hauled work and not one of those blocks was
operable by a single type of equipment. Redlands has not vanished from the
picture, though — trips 309 and 342 are locomotive-hauled San Bernardino Line
runs extended to Redlands - Downtown, which is why one block still starts there
and one still ends there.

### What deadheading buys

The zero-depot result assumes a set can only pick up a trip where it last
stopped. `preformulation.py` also builds a second arc set that drops that
restriction. A chaining is legal when the gap between trip times covers a
turnaround, the empty move, and another turnaround. Only stations actually 
served that Monday are in the graph, so no set ever deadheads down a line 
the schedule does not use.

That triples the arc set, from **2,115 chainings to 5,316**, and
`zero_depot_deadheading.py` solves the same LP over it. The fleet falls from
**35 to 31** — four trainsets, 11%. It is the same minimum-path-cover LP with a
looser feasibility rule, so 31 is a lower bound on 35 by construction; the
question is what it costs.

**The blocks get uniform.** `viz/zero_depot_deadheading_viz.py` reports the same
distribution the base model does, and the contrast is sharper than the fleet
count:

| | No deadheading | Deadheading |
| --- | --- | --- |
| Blocks | 35 | 31 |
| Trips per block | 2 – 7 | 3 – 6 |
| Mean / median | 3.77 / 4.0 | 4.26 / 4.0 |
| Stdev | 1.24 | 0.73 |
| IQR (Q1–Q3) | 2.0 (3–5) | 1.0 (4–5) |
| Span | 3:43 – 18:18 (median 13:18) | 10:45 – 18:31 (median 14:02) |
| Revenue share of block-hours | 225 / 445 h = 51% | 225 / 433 h = 52% |

Both distributions are outlier-free under Tukey, but the deadheading one is
half as dispersed — the fences close from [0, 8] to [2.5, 6.5]. The four sets
come out of the *short* end of the distribution, not the long one: the base
model's five two-trip blocks are gone, and the shortest duty in the day goes
from 3h43m to 10h45m. Deadheading does not lengthen the day's longest work, it
deletes the stub duties by giving them somewhere to go.

**Utilisation barely moves.** Revenue hours are fixed at 225 by the schedule, so
spreading them over 31 sets instead of 35 only lifts the revenue share of
block-time from 51% to 52%. The saving is real, but it is a saving in *sets*,
not in idleness — the same fleet-wide slack is simply cut into fewer pieces.

**Empty mileage is the bill.** The solution uses 101 turns, of which **39 are
deadheads** and 62 are ordinary same-station turns. Those 39 moves total
**61.3 hours of empty running**, averaging 94 minutes each, and each one also
burns two 20-minute turnarounds on top. Roughly 15 hours of empty running per
trainset saved, before crew, fuel, or a dispatcher's willingness to path it.
The extremes are not marginal repositionings:

| Move | Empty running | Gap available |
| --- | --- | --- |
| Lancaster → Moorpark | 2:48 | 5:20 |
| Vista Canyon → Riverside - Downtown | 2:37 | 4:04 |
| Moorpark → Laguna Niguel / Mission Viejo | 2:35 | 4:43 |
| Riverside - Downtown → Chatsworth | 2:17 | 3:30 |

A Lancaster-to-Moorpark light move crosses the whole north end of the system on
BNSF and UP trackage to save one set, and the model prices it purely in minutes.

**The day stops balancing.** This is the finding that most undercuts the 31.
Under the base model the multiset of block origins equalled the multiset of
termini at every one of the eleven endpoint stations, so 35 sets was a genuine
steady state that repeats the next morning untouched. With deadheading it does
not: LAUS ends the day with **7 blocks terminating against 3 originating**,
while Riverside is short 2, and Perris and Laguna Niguel short 1 each. Four sets
finish out of position — exactly as many as the model saved — and putting them
back is four more overnight deadheads the objective never sees. The LP maximises
chainings inside one day, so it happily spends tomorrow's position to buy today's
match.

**It does fix the stranded endpoints, and create a new one.** The base model
left five blocks starting or ending at Chatsworth, Vista Canyon, or Redlands -
Downtown, none of them documented stabling. Chatsworth and Vista Canyon stop
being endpoints entirely here — deadheads absorb them mid-block (L.A. → Vista
Canyon, Vista Canyon → Riverside, Riverside → Chatsworth, Chatsworth → L.A.),
which is precisely the repositioning the base model could not price and flagged
as missing. Redlands survives, since trips 309 and 342 genuinely start and end
there. But Laguna Niguel / Mission Viejo takes their place: it is a mid-line
Orange County station with no storage, it now originates a block, and seven of
the 39 deadheads route through it. The model has traded three implausible
endpoints for one implausible hub.

So 31 is the right answer to the question as posed and the wrong number to plan
against. Metrolink's own weekday floor was 36. The honest reading is that the
gap between 35 and 31 measures how much of the fleet exists to avoid empty
mileage rather than to carry passengers — and that the four sets are only
recoverable by an operator willing to run 61 hours of light engine moves a day
and reposition four more sets overnight.

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
│   │                             shortest path over mean station-to-station running times
│   ├── zero_depot.py             Builds and solves the min-path-cover LP; reports the fleet
│   │                             size, the blocks, and their origins/termini/spans
│   ├── zero_depot_deadheading.py The same LP over the deadheading arc set (asserts 31)
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
├── pytest.ini                    Points pytest at tests/ and puts src/ on sys.path
├── PuLP_solver_files/            Saved MPS export of the LP, for inspection
└── misc/                         Scratch work
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
python src/zero_depot_deadheading.py          # the same LP with deadheading (asserts 31)
python src/viz/zero_depot_deadheading_viz.py  # figures/block_lengths_deadheading.png
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
