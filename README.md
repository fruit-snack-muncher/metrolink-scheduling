# metrolink-scheduling

How few trainsets does it take to operate a full weekday of Metrolink service?

This repository answers that question for the Southern California Metrolink
network from its published GTFS feed. The pipeline picks a *typical Monday* out
of the feed — Oct 19, 2026, chosen because the set of services scheduled that
day is identical before and after applying the feed's service exceptions, so it
represents ordinary operation rather than a holiday or a special event. That day
carries **178 trips** across the seven Metrolink lines.

Each trip is reduced to the only four facts that matter for equipment planning:
the station it departs from, the station it arrives at, and the two clock times,
expressed in seconds past midnight. Two trips can be run back-to-back by the
same trainset when the first *ends* where the second *begins* and there are at
least 20 minutes between the arrival and the following departure — enough to
change ends and service the set. The turnaround is a **lower** bound only: a set
that lays over at Lancaster from morning until evening is a legal, if idle,
chain, and on the outer ends of the AV and VC lines it is a necessary one.
Applying that rule to all 178² ordered pairs yields **2,846 valid chainings**.

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
deadheading, is **38 trainsets** for 178 trips.

### Modelling assumptions

The count is a lower bound on real equipment needs, not an operating plan.
Deadheading (repositioning an empty set) is not modelled, so a set can only pick
up a trip where it last stopped. Consist size, maintenance windows, crew rules,
and yard capacity are all out of scope, and every set is treated as
interchangeable. `TURNAROUND` in [src/preformulation.py](src/preformulation.py) is the
single knob controlling how conservative the result is; raising it can only
remove chaining opportunities, never create them, so the fleet count moves
monotonically with it.

### Are the blocks operable?

`zero_depot_fleet.py` prints where each block starts, where it ends, and its
**span** — first departure to last arrival. Three things stand out.

**The day balances.** The multiset of origins is exactly the multiset of
termini: 12 blocks start at San Bernardino and 12 end there, 6 and 6 at LAUS,
and so on across all twelve stations involved. Nothing needs repositioning
overnight for the schedule to repeat, so 38 sets is a steady state rather than a
one-day trick — and nothing in the model asked for it, it falls out of the
matching. It
also means the blocks chain into **rotations**: seven return to their own origin
(two via triangles rather than out-and-backs, which is why they carry an odd
number of trips), and the other 31 decompose into cycles — eight two-day pairs,
one three-day, one four-day, one eight-day. The fleet is 18 pools, not 38
independent duties, though only the two-day pairs are forced; the longer cycles
are one valid decomposition among several. Rotation length is a cost in itself:
the eight-day loop runs Perris → Riverside → Ventura → San Bernardino →
Moorpark → LAUS → Chatsworth → Redlands, collecting the three stations that
appear exactly once in the schedule and so cannot pair off with anything.

**Most endpoints are real stabling points.** Metrolink overhauls equipment at
the [Central Maintenance Facility](https://metrolinktrains.com/community-main/cmf/)
beside LAUS and at the Eastern Maintenance Facility in Colton, minutes from San
Bernardino - Downtown, and stables sets overnight at Lancaster, East Ventura,
Moorpark, Riverside, Perris Valley, and Stuart Mesa north of Oceanside. That
covers both ends of 31 of the 38 blocks. The rest begin or end at Chatsworth,
Vista Canyon, or one of the two Redlands stations — none a documented storage
location — so those sets need a deadhead the model does not price.

**The long blocks are the questionable ones.** Spans run 3:43 to 19:21 (median
14:18), and fleet-wide the sets are in revenue service for 242 of 514
block-hours, or 47%. That idleness is normal for peak-heavy commuter rail and is
exactly what buys the low fleet count. But five blocks span 16 hours or more,
and what constrains them is the gap to whatever the set does next in its
rotation — not 24 hours minus the span. The three tightest:

| Block | Span | Endpoints | Next duty | Overnight |
| --- | --- | --- | --- | --- |
| 30 | 19:21 | Redlands - University → San Bernardino | blk 33 | 6:13 |
| 29 | 18:50 | San Bernardino → San Bernardino | itself | 5:10 |
| 33 | 17:18 | San Bernardino → Redlands - University | blk 30 | 5:08 |

[49 CFR 238.303](https://www.ecfr.gov/current/title-49/subtitle-B/chapter-II/part-238/subpart-D/section-238.303)
requires an exterior mechanical inspection once each calendar day the equipment
is in service, and fueling, cleaning, and brake tests want the same window. The
binding case is the tightest handoff rather than the longest block: Block 33
arrives at Redlands - University at 23:00 and Block 30 leaves at 04:08, giving
5h08m at a station with no facility. Thin but not disqualifying — the inspection
is per calendar day, not a rolling 24 hours. The sharper constraint is that the
outer layovers are storage tracks with no fueling, so a set stabled at Lancaster
or Perris is on a multi-day cycle back to CMF or EMF that a single-day model
cannot see.

Two caveats outweigh all of this. The feed files the Redlands **Arrow** trips
under the San Bernardino Line rather than a route of their own, so nothing marks
them as a separate fleet: all 48 land in blocks that also contain
locomotive-hauled trips, and not one of those 13 blocks is operable by a single
type of equipment. Arrow runs DMUs, so those blocks are arithmetic, not
schedules. And none of this leaves the typical weekday — Saturday and Sunday
carry 92 trips each against 178, which `services_active_on` in
[src/data_collection.py](src/data_collection.py) cannot even evaluate, since it
indexes `calendar.txt` by a five-element weekday list; the 14 dates in
`calendar_dates.txt` that change service are likewise never examined. A real
fleet is sized for the busiest day of the week, holidays and special events
included.

## Layout

```
metrolink/
├── gtfs_raw/                     Metrolink GTFS feed, exactly as published
├── gtfs_cleaned/                 Working copy of the feed, plus derived data
│   └── typical_monday.txt          Trips active on Oct 19, 2026 (written by data_collection.py)
├── src/
│   ├── data_collection.py        Resolves calendar.txt + calendar_dates.txt into the
│   │                             services active on a given day; finds and writes the typical Monday
│   ├── typical_monday_trips.py   Reduces each typical-Monday trip to
│   │                             (departure stop, arrival stop, departure time, arrival time)
│   ├── preformulation.py         valid_pair() — the chaining rule; builds the arc set of the DAG
│   ├── zero_depot_fleet.py       Builds and solves the min-path-cover LP; reports the fleet
│   │                             size, the blocks, and their origins/termini/spans
│   ├── zero_depot_fleet_visualization.py
│   │                             Block-length statistics and bar chart
│   ├── fleet_min-pulp.sol        CBC's solution to that LP, kept for inspection
│   └── conftest.py               Puts src/ on sys.path for the test suite
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
python src/zero_depot_fleet.py     # solves the LP (asserts the fleet size is 38)
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
