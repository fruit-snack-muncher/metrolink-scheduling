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
│   ├── zero_depot_fleet.py       Builds and solves the min-path-cover LP; reports the fleet size
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

PuLP ships with the [CBC](https://github.com/coin-or/Cbc) mixed-integer solver,
which is what actually solves the LP here — no separate solver install is
needed. NumPy comes along as a pandas dependency.

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
