"""The fleet-minimization LP, shared by every solver variant.

Trips are nodes and legal chainings are directed arcs; the DAG is acyclic
because no chain can go back in time. Covering the trips with as few paths as
possible is the same problem as choosing as many arcs as possible, and each
variant differs only in which arcs it offers and what it weighs them by.

Solved in TWO STAGES, because the answer is badly degenerate. Stage 1 maximizes
the bare arc count, which is exactly what the fleet size measures. Stage 2 then
optimizes the variant's own weights *subject to that count*, choosing among the
minimum-fleet solutions rather than trading fleet size against arc weight.

Both halves of that matter. Blending the two into one objective - maximize
`(chainings) - (deadhead hours) x rate` - does not actually guarantee the fleet
size it reports: a solution with one arc fewer and enough deadheading saved
scores identically, and would return a larger fleet. And leaving stage 2 off
entirely leaves the solution arbitrary, since the minimum-fleet solutions here
span 06:08:53 to 109:56:40 of deadheading. Which one CBC returns depends on its
build, so any assertion about the solution's *composition* is unreproducible
across machines without stage 2.

The stages are built as two SEPARATE problems, because they are not the same
kind of problem: pinning the arc count costs total unimodularity, and with it
the right to solve the thing as a continuous LP. See _path_cover_model.

Individual arcs can be pinned at 0 or 1 through `forced`, which is what the
sensitivity study in analysis/forcing/forcing_sweep.py is built on: mandate or forbid one
chaining, re-solve, and see whether the minimum fleet and the stage 2 optimum
survive it. Forcing can make the problem infeasible, so `solve` returns a status
rather than asserting one.
"""

from typing import NamedTuple

import pulp


class Solution(NamedTuple):
    """What one (possibly forced) run of `solve` found.

    Everything but `status` is None when the forcing made the problem infeasible.
    `chained` and `objective` are what the sweep compares against an unforced
    baseline: the first says whether the minimum fleet is still reachable, the
    second whether the variant's own optimum is.
    """
    status: str                              # a pulp.LpStatus string
    fleet_size: int | None
    chained: int | None                      # stage 1's optimum: arcs used
    objective: float | None                  # weighted objective of the returned solution
    arcs: list[tuple[int, int]] | None


def _path_cover_model(name: str, trip_ids: list[int],
                      weighted_arcs: list[tuple[float, tuple[int, int]]],
                      category: str,
                      forced: dict[tuple[int, int], int] | None = None) -> tuple[pulp.LpProblem, dict]:
    """One path-cover feasible region: a variable per arc, at most one arc into
    each trip and one out of it. A trainset can neither run two trips at once nor
    be in two places, and that is the whole of it - the objective is the caller's.

    `category` is the only thing separating the two stages. Every column here holds
    exactly two 1's, one among the |trips| departing rows and one among the |trips|
    arriving rows, which makes the stage 1 constraint matrix totally unimodular,
    giving an integral relaxation. Stage 2 appends a row with a 1 in *every* column,
    breaking the TU structure; it forces integral decision variables and continues.

    `forced` maps an arc to the 0 or 1 it is pinned at.
    """
    prob = pulp.LpProblem(name, pulp.LpMaximize)
    var = pulp.LpVariable.dict("x", [str(arc) for _, arc in weighted_arcs],
                               lowBound=0, upBound=1, cat=category)

    # Pinned by their BOUNDS, not by an added row, and the difference is the same one the
    # module docstring makes about stage 2's minimum_fleet row. Fixing a variable deletes
    # its column and moves the RHS by an integer, so what is left is a submatrix of a
    # totally unimodular matrix and stage 1 may stay Continuous. A row saying x == 1 would
    # destroy that structure and put stage 1 into a branch-and-bound it does not need.
    for arc, value in (forced or {}).items():
        # KeyError here is the right failure: an arc absent from weighted_arcs has no
        # variable to force, and silently ignoring it would report a forcing never applied.
        pinned = var[str(arc)]
        pinned.lowBound = pinned.upBound = value

    departures = {str(t): [] for t in trip_ids}
    arrivals = {str(t): [] for t in trip_ids}
    for _, (tripA, tripB) in weighted_arcs:
        departures[str(tripA)].append(var[str((tripA, tripB))])
        arrivals[str(tripB)].append(var[str((tripA, tripB))])

    for t in map(str, trip_ids):
        if departures[t]:
            prob.addConstraint(pulp.lpSum(departures[t]) <= 1, name=f"departing_{t}")
        if arrivals[t]:
            prob.addConstraint(pulp.lpSum(arrivals[t]) <= 1, name=f"arriving_{t}")

    return prob, var


def solve(trip_ids: list[int], weighted_arcs: list[tuple[float, tuple[int, int]]],
          forced: dict[tuple[int, int], int] | None = None) -> Solution:
    """Minimum path cover over the trip DAG, ties broken by arc weight.

    `weighted_arcs` is a list of (weight, (tripA, tripB)). `forced` optionally pins
    arcs at 0 or 1, mandating or forbidding those chainings. Returns a Solution:
    each chosen arc chains two trips, so it removes one trainset from the fleet.
    Uniform weights skip stage 2, which would have nothing to choose between.
    """
    # STAGE 1: the fleet size itself. Every arc counts for one, so the objective is the
    # chaining count and its optimum is the true minimum fleet, whatever the weights say.
    prob1, var1 = _path_cover_model("fleet_min", trip_ids, weighted_arcs, "Continuous", forced)
    prob1.setObjective(pulp.lpSum(var1.values()))

    # Turn keepFiles on to see the solver files; they land in the working directory.
    prob1.solve(pulp.PULP_CBC_CMD(msg=0, keepFiles=False))
    # Unforced this is always Optimal - the all-zero solution is feasible. Forcing an arc
    # to 1 can genuinely conflict with another forcing, and that is a finding to report,
    # not a bug to assert on.
    if pulp.LpStatus[prob1.status] != "Optimal":
        return Solution(pulp.LpStatus[prob1.status], None, None, None, None)
    chained = round(pulp.value(prob1.objective))

    # STAGE 2: among the solutions that achieve that fleet, the one this variant prefers.
    # A second problem over the same feasible region, plus the row that holds the fleet
    # at stage 1's answer. Being integral, that row can be an exact equality: no tolerance
    # is needed to survive floating-point, and none should be offered, since slack here is
    # exactly what would let stage 2 buy its weights back with a trainset.
    #
    # Uniform weights - the no-deadheading and unpenalised variants - have no preference
    # to express, and re-solving would only pick another arbitrary point on the same
    # optimal face, so they keep stage 1's answer.
    weights = [weight for weight, _ in weighted_arcs]
    if min(weights) != max(weights):
        prob2, var2 = _path_cover_model("fleet_min_weighted", trip_ids, weighted_arcs, "Integer", forced)
        prob2.addConstraint(pulp.lpSum(var2.values()) == chained, name="minimum_fleet")
        prob2.setObjective(pulp.lpSum(weight * var2[str(arc)] for weight, arc in weighted_arcs))
        prob2.solve(pulp.PULP_CBC_CMD(msg=0, keepFiles=False))
        # Stage 1's own solution satisfies every row here, so infeasibility would mean the
        # two stages disagree about the feasible region. Still returned rather than
        # asserted, so one bad point cannot take a whole sweep down.
        if pulp.LpStatus[prob2.status] != "Optimal":
            return Solution(pulp.LpStatus[prob2.status], None, None, None, None)
        chosen = var2
    else:
        chosen = var1

    # Count the arcs rather than reading pulp.value(prob.objective): after stage 2 the
    # objective is a weighted sum, not a chaining count.
    # >= 0.5 rather than == 1 to absorb floating-point error.
    chosen_arcs = [arc for _, arc in weighted_arcs if chosen[str(arc)].varValue >= 0.5]
    assert len(chosen_arcs) == chained, f"stage 2 returned {len(chosen_arcs)} arcs, not {chained}"

    # Read off the chosen arcs rather than the problem's objective, so the number means the
    # same thing on both branches: the uniform-weight path never built the weighted
    # objective, and a sweep comparing forced runs against a baseline needs one scale.
    objective = sum(weight for weight, arc in weighted_arcs if chosen[str(arc)].varValue >= 0.5)
    return Solution("Optimal", len(trip_ids) - len(chosen_arcs), chained, objective, chosen_arcs)
