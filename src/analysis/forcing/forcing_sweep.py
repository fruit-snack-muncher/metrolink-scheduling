"""What each single decision would cost: one forced re-solve per variable per value.

The solvers answer what the minimum fleet is and which minimum-fleet day is cheapest.
This asks the question underneath that: if one chaining, depot departure, or depot
arrival were MANDATED (forced to 1) or FORBIDDEN (forced to 0), is the schedule still
feasible, does it still reach the minimum fleet, and does it still reach the variant's
own optimum? A variable whose forcing costs nothing is a free choice the planner may
make on other grounds; one that costs a trainset is load-bearing.

Every point is an independent re-solve of a whole problem, so this is long-running by
construction: ~4k points for zero_depot, ~10k for each deadheading variant, ~22k for
multi_depot at ~3 s each. Hence the two things that make it survivable - a CSV appended
and flushed row by row, re-read on the next run to skip what is already done, and a
process pool over the points, which are independent.

ONE SHORTCUT is sound and is taken: if the unforced baseline already has the variable at
the value being forced, the baseline solution is itself a witness that everything is
reachable, and no solve is needed. Every other point is solved for real.

A NOTE ON THE UNIFORM-WEIGHT PROBLEMS. zero_depot and deadheading_unweighted weigh every
arc the same, so min_path_cover skips stage 2 and the objective is just the chaining
count scaled. Their `objective_reachable` column is therefore not a second finding - it
is `min_fleet_reachable` restated, and should be read as such. Only
deadheading_penalised and multi_depot answer the two questions separately.

    python -m src.analysis.forcing.forcing_sweep --status                     # what is done so far
    python -m src.analysis.forcing.forcing_sweep --problem zero_depot
    python -m src.analysis.forcing.forcing_sweep --problem multi_depot --workers 8
    python -m src.analysis.forcing.forcing_sweep --problem all --limit 50     # smoke run

DO NOT EDIT THIS MODULE, OR ANYTHING IT IMPORTS, WHILE A RUN IS IN FLIGHT. Workers are
spawned, not forked, so each one re-imports the source FROM DISK as it starts - a pool that
outlives an edit ends up running two different versions of this file, and a worker that
imports a half-written file dies on a SyntaxError. A multi-hour run is exactly long enough
to forget this. It has already cost one sweep.
"""

import argparse
import csv
import multiprocessing
import signal
from pathlib import Path
from typing import Callable, NamedTuple

from src.analysis.markdown_report import REPORTS

# Taken from markdown_report rather than derived from this module's own __file__, which is
# what it used to be. A path built from __file__ silently follows the module when it moves:
# this file moving into analysis/forcing/ would have redirected the sweep to a brand new
# empty tree at analysis/forcing/reports/sweeps, beside the real results rather than erroring.
# One module now knows where output lives, and it is the one that never moves.
SWEEPS = REPORTS / "sweeps"

# Baselines are floats built from deadhead seconds, and a forced re-solve reaches the same
# optimum by a different arithmetic path, so equality has to be relative.
TOLERANCE = 1e-6

PROBLEM_NAMES = ["zero_depot", "deadheading_penalised", "deadheading_unweighted", "multi_depot"]

# Forbidden, then mandated. Shared by `points`, which queues them, and by `expected_points`,
# which counts them without building anything - the two must never disagree about how many
# times a single variable is visited.
FORCED_VALUES = (0, 1)

FIELDS = ["family", "variable", "forced_value", "status", "fleet_size", "chained",
          "objective", "min_fleet_reachable", "objective_reachable", "solved"]


class Problem(NamedTuple):
    """One sweepable problem: its baseline, its variables, and how to re-solve it.

    Built inside each worker process rather than passed to one - the closures below are
    not picklable, and a spawned worker has to import the solver module anyway.
    """
    baseline: object                                   # a solver Solution: .chained, .objective
    families: dict[str, list]                          # family -> its variable keys
    solve: Callable[[str, tuple, int], object]         # (family, key, value) -> Solution
    baseline_value: Callable[[str, tuple], int]        # what the baseline solution has there


# ==============================================================================
#
# THE FOUR PROBLEMS.
#
# ==============================================================================
#
# Imports are deferred into these builders on purpose. Each solver module solves at import
# time, so importing all four at module scope would make even `--help` pay for four
# baselines, and would make every pool worker pay for the three problems it is not running.

def _zero_depot() -> Problem:
    from src.solvers.min_path_cover import solve
    from src.solvers.zero_depot import solution, weighted_arcs
    from src.data_processing.typical_monday_trips import typical_monday_trip_ids
    return _path_cover_problem(typical_monday_trip_ids, weighted_arcs, solution, solve)


def _deadheading_penalised() -> Problem:
    from src.solvers.min_path_cover import solve
    from src.solvers.zero_depot_deadheading import penalised
    from src.data_processing.preformulation import weights_and_arcs
    from src.data_processing.typical_monday_trips import typical_monday_trip_ids
    return _path_cover_problem(typical_monday_trip_ids, weights_and_arcs, penalised, solve)


def _deadheading_unweighted() -> Problem:
    from src.solvers.min_path_cover import solve
    from src.solvers.zero_depot_deadheading import unweighted, unweighted_weights_and_arcs
    from src.data_processing.typical_monday_trips import typical_monday_trip_ids
    return _path_cover_problem(typical_monday_trip_ids, unweighted_weights_and_arcs, unweighted, solve)


def _path_cover_problem(trip_ids, weighted_arcs, baseline, solve) -> Problem:
    """The three zero-depot variants differ only in their arc set and weights."""
    chosen = set(baseline.arcs)
    return Problem(
        baseline=baseline,
        families={"chaining": [arc for _, arc in weighted_arcs]},
        solve=lambda family, key, value: solve(trip_ids, weighted_arcs, forced={key: value}),
        baseline_value=lambda family, key: int(key in chosen),
    )


def _multi_depot() -> Problem:
    import src.solvers.multi_depot as md

    # The solver hands its labels back trip -> depot; the variables are keyed the other way.
    chosen = {
        "chaining": set(md.chained_arcs),
        "departure": {(depot, trip) for trip, depot in md.home_depots.items()},
        "arrival": {(depot, trip) for trip, depot in md.terminal_depots.items()},
    }
    keyword = {"chaining": "forced_chainings",
               "departure": "forced_departures",
               "arrival": "forced_arrivals"}

    return Problem(
        baseline=md.baseline,
        families={
            "chaining": list(md.multi_depot_arcs),
            "departure": [(depot, trip) for depot, (trip,) in md.multi_depot_departures],
            "arrival": [(depot, trip) for depot, (trip,) in md.multi_depot_arrivals],
        },
        solve=lambda family, key, value: md.solve(**{keyword[family]: {key: value}}),
        baseline_value=lambda family, key: int(key in chosen[family]),
    )


BUILDERS = {"zero_depot": _zero_depot,
            "deadheading_penalised": _deadheading_penalised,
            "deadheading_unweighted": _deadheading_unweighted,
            "multi_depot": _multi_depot}


# ==============================================================================
#
# ONE POINT OF THE SWEEP.
#
# ==============================================================================

# Built once per process and kept: a worker handles many points of the same problem, and
# rebuilding would re-solve the baseline every time. Module-global rather than passed,
# because it is exactly what cannot cross a process boundary.
_problem: Problem | None = None
_problem_name: str | None = None


def _load(name: str) -> Problem:
    global _problem, _problem_name
    if _problem_name != name:
        _problem, _problem_name = BUILDERS[name](), name
    return _problem


def _initializer() -> None:
    """Ignore Ctrl+C in workers, and do NOTHING ELSE.

    Ctrl+C reaches every process in the group, so a worker that handles it prints its own
    traceback and the terminal fills with one stack per worker on top of the parent's.
    Ignoring it here leaves the interrupt to the parent alone, which shuts the pool down
    and reports what was saved. Workers still die - `pool.terminate()` does not go through
    SIGINT - they just stop narrating it.

    Nothing fallible belongs in here, and the emptiness is the point. A Pool REPOPULATES a
    worker that dies, so an initializer that raises is retried forever: the worker dies, is
    replaced, dies again, and the terminal fills with thousands of identical tracebacks
    while the run never finishes or fails. Loading the problem used to happen here, and it
    is exactly the fallible kind of work that triggers that - it imports pandas, reads the
    GTFS tables and solves a baseline. It now happens lazily in `evaluate`, where a failure
    travels back to the parent as one ordinary exception.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def evaluate(point: tuple[str, str, tuple, int]) -> dict:
    """Re-solve one problem with one variable pinned, and report what it cost.

    `point` is (problem_name, family, variable_key, forced_value), all picklable - it is
    what crosses into the pool. The Problem itself is rebuilt on the far side by _load.
    """
    name, family, key, value = point
    problem = _load(name)
    baseline = problem.baseline

    row = {"family": family, "variable": repr(key), "forced_value": value}

    # The one sound shortcut: the baseline already does this, so it is its own witness.
    if problem.baseline_value(family, key) == value:
        return row | {"status": baseline.status,
                      "fleet_size": baseline.fleet_size,
                      "chained": baseline.chained,
                      "objective": baseline.objective,
                      "min_fleet_reachable": True,
                      "objective_reachable": True,
                      "solved": False}

    forced = problem.solve(family, key, value)
    if forced.status != "Optimal":
        return row | {"status": forced.status,
                      "fleet_size": None, "chained": None, "objective": None,
                      "min_fleet_reachable": False,
                      "objective_reachable": False,
                      "solved": True}

    return row | {"status": forced.status,
                  "fleet_size": forced.fleet_size,
                  "chained": forced.chained,
                  "objective": forced.objective,
                  "min_fleet_reachable": forced.chained == baseline.chained,
                  # A forced optimum can never BEAT the baseline - forcing only removes
                  # solutions - so reaching it means matching it.
                  "objective_reachable": abs(forced.objective - baseline.objective)
                                         <= TOLERANCE * max(1.0, abs(baseline.objective)),
                  "solved": True}


# ==============================================================================
#
# THE SWEEP.
#
# ==============================================================================

def points(name: str, problem: Problem) -> list[tuple[str, str, tuple, int]]:
    """Every variable of every family, forbidden and then mandated."""
    return [(name, family, key, value)
            for family, keys in problem.families.items()
            for key in keys
            for value in FORCED_VALUES]


def expected_points(name: str) -> int:
    """How many rows a FINISHED sweep of `name` holds - without building anything.

    Counted from the arc lists rather than from a Problem, because building a Problem solves
    that problem's baseline, and `--status` exists to answer a question about files in a
    couple of seconds. Four baselines, one of them a pair of MILPs, is not that.

    The price of the shortcut is a second place that knows how the points are enumerated, so
    `sweep` cross-checks this against the real `points()` whenever it loads a problem.
    """
    from src.data_processing.preformulation import (multi_depot_weighted_arrivals,
                                                    multi_depot_weighted_departures,
                                                    multi_weights_and_arcs, valid_arcs,
                                                    weights_and_arcs)
    variables = {
        "zero_depot": len(valid_arcs),
        "deadheading_penalised": len(weights_and_arcs),
        "deadheading_unweighted": len(weights_and_arcs),
        "multi_depot": (len(multi_weights_and_arcs)
                        + len(multi_depot_weighted_departures)
                        + len(multi_depot_weighted_arrivals)),
    }
    return variables[name] * len(FORCED_VALUES)


def rows_on_disk(path: Path) -> list[dict]:
    """Every row a sweep CSV already holds, or [] if it holds none.

    The size check is not redundant: a run killed during pool startup can leave a 0-byte
    file, which has no header for DictReader to key rows by.
    """
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def completed(path: Path) -> set[tuple[str, str, str]]:
    """The (family, variable, forced_value) of every row already on disk.

    Read as text exactly as it was written, so the comparison in `sweep` is between two
    strings and never depends on repr() round-tripping through a Python literal.
    """
    return {(row["family"], row["variable"], row["forced_value"]) for row in rows_on_disk(path)}


def status() -> None:
    """How far each problem has got, read off the CSVs without solving anything."""
    print(f"{'problem':<24}{'rows':>7} /{'total':>7}          state")
    for name in PROBLEM_NAMES:
        path = SWEEPS / f"{name}.csv"
        rows = rows_on_disk(path)
        keys, total = completed(path), expected_points(name)

        if not rows:
            state = "not started"
        elif len(keys) >= total:
            state = "complete"
        else:
            state = "incomplete - re-run to resume"

        # Both are silent-corruption checks, not progress: duplicates would mean the resume
        # filter let a point through twice, and a row without a status was never filled in.
        if len(keys) != len(rows):
            state += f"  [{len(rows) - len(keys)} DUPLICATE ROWS]"
        malformed = sum(1 for row in rows if not row.get("status"))
        if malformed:
            state += f"  [{malformed} MALFORMED ROWS]"

        print(f"{name:<24}{len(keys):>7} /{total:>7}  ({100 * len(keys) / total:5.1f}%)  {state}")


def sweep(name: str, workers: int, limit: int | None) -> None:
    """Run one problem's sweep to its CSV, resuming whatever is already there."""
    SWEEPS.mkdir(parents=True, exist_ok=True)
    path = SWEEPS / f"{name}.csv"

    problem = _load(name)
    all_points = points(name, problem)
    # The one place both enumerations exist at once, so --status can never quietly report a
    # denominator this run would not actually fill.
    assert len(all_points) == expected_points(name), (
        f"expected_points({name}) says {expected_points(name)}, but the problem enumerates "
        f"{len(all_points)}; --status would report against the wrong total")

    done = completed(path)
    todo = [point for point in all_points
            if (point[1], repr(point[2]), str(point[3])) not in done]
    if limit is not None:
        todo = todo[:limit]

    print(f"{name}: baseline {problem.baseline.chained} chainings, "
          f"objective {problem.baseline.objective:.6f}")
    print(f"{name}: {len(todo)} points to solve, {len(done)} already on disk")
    if not todo:
        return

    # Appended and flushed row by row. A sweep that has to be killed after two hours should
    # keep its two hours.
    pool = None
    written = 0
    interrupted = False
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not done:
            writer.writeheader()
            # Flushed at once, so a run that dies during pool startup leaves a file holding
            # its header rather than zero bytes. The difference matters when reading the
            # wreckage later: a header says "started, got nowhere", while an empty file is
            # indistinguishable from one nothing ever opened.
            f.flush()

        if workers == 1:
            results = map(evaluate, todo)
        else:
            # Each worker loads the problem on its first point and caches it, so the
            # baseline is paid once per worker rather than once per point - see _load, and
            # see _initializer for why that load is not done in the initializer.
            pool = multiprocessing.Pool(workers, initializer=_initializer)
            results = pool.imap_unordered(evaluate, todo, chunksize=8)

        infeasible = unreachable = 0
        try:
            for row in results:
                writer.writerow(row)
                f.flush()
                written += 1
                infeasible += row["status"] != "Optimal"
                unreachable += row["status"] == "Optimal" and not row["min_fleet_reachable"]
                if written % 100 == 0 or written == len(todo):
                    print(f"  {written}/{len(todo)}  {infeasible} infeasible, "
                          f"{unreachable} feasible but over minimum fleet")
        except KeyboardInterrupt:
            # Expected, on a sweep long enough that stopping it is a normal thing to do.
            # Swallowed rather than re-raised so `--problem all` reports this problem's
            # progress and stops, instead of unwinding through argparse's caller.
            interrupted = True
        finally:
            # terminate(), not close(): close() waits for every point already handed out,
            # which after an interrupt is up to `chunksize` solves per worker.
            if pool is not None:
                pool.terminate()
                pool.join()

    if interrupted:
        # In-flight points are simply lost, not corrupted - each row is written whole, and
        # the next run re-reads the file and re-queues whatever is missing.
        print(f"\n{name}: interrupted, {written} new rows saved to {path}")
        print(f"{name}: re-run the same command to resume from there")
        raise SystemExit(130)

    print(f"{name}: wrote {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--problem", default="all", choices=PROBLEM_NAMES + ["all"])
    parser.add_argument("--workers", type=int, default=max(1, (multiprocessing.cpu_count() or 2) - 1),
                        help="processes to solve on; 1 runs in-process, which is what to debug with")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many points, for a smoke run")
    parser.add_argument("--status", action="store_true",
                        help="report how complete every problem's CSV is, and solve nothing")
    args = parser.parse_args()

    if args.status:
        # Reports on all four regardless of --problem: the question it answers is about the
        # sweep as a whole, and defaulting to one problem would hide the other three.
        status()
        raise SystemExit(0)

    for problem_name in (PROBLEM_NAMES if args.problem == "all" else [args.problem]):
        sweep(problem_name, args.workers, args.limit)
