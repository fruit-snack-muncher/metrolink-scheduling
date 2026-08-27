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
"""

import pulp


def _path_cover_model(name: str, trip_ids: list[int],
                      weighted_arcs: list[tuple[float, tuple[int, int]]],
                      category: str) -> tuple[pulp.LpProblem, dict]:
    """One path-cover feasible region: a variable per arc, at most one arc into
    each trip and one out of it. A trainset can neither run two trips at once nor
    be in two places, and that is the whole of it - the objective is the caller's.

    `category` is the only thing separating the two stages. Every column here holds 
    exactly two 1's, one among the |trips| departing rows and one among the |trips| 
    arriving rows, which makes the stage 1 constraint matrix totally unimodular,
    giving an integral relaxation. Stage 2 appends a row with a 1 in *every* column, 
    breaking the TU structure; it forces integral decision variables and continues.
    """
    prob = pulp.LpProblem(name, pulp.LpMaximize)
    var = pulp.LpVariable.dict("x", [str(arc) for _, arc in weighted_arcs],
                               lowBound=0, upBound=1, cat=category)

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


def solve(trip_ids: list[int], weighted_arcs: list[tuple[float, tuple[int, int]]]) -> tuple[int, list[tuple[int, int]]]:
    """Minimum path cover over the trip DAG, ties broken by arc weight.

    `weighted_arcs` is a list of (weight, (tripA, tripB)). Returns
    (fleet_size, chosen_arcs): each chosen arc chains two trips, so it removes
    one trainset from the fleet. Uniform weights skip stage 2, which would have
    nothing to choose between.
    """
    # STAGE 1: the fleet size itself. Every arc counts for one, so the objective is the
    # chaining count and its optimum is the true minimum fleet, whatever the weights say.
    prob1, var1 = _path_cover_model("fleet_min", trip_ids, weighted_arcs, "Continuous")
    prob1.setObjective(pulp.lpSum(var1.values()))

    # Turn keepFiles on to see the solver files; they land in the working directory.
    prob1.solve(pulp.PULP_CBC_CMD(msg=0, keepFiles=False))
    assert pulp.LpStatus[prob1.status] == "Optimal"
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
        prob2, var2 = _path_cover_model("fleet_min_weighted", trip_ids, weighted_arcs, "Integer")
        prob2.addConstraint(pulp.lpSum(var2.values()) == chained, name="minimum_fleet")
        prob2.setObjective(pulp.lpSum(weight * var2[str(arc)] for weight, arc in weighted_arcs))
        prob2.solve(pulp.PULP_CBC_CMD(msg=0, keepFiles=False))
        assert pulp.LpStatus[prob2.status] == "Optimal"
        chosen = var2
    else:
        chosen = var1

    # Count the arcs rather than reading pulp.value(prob.objective): after stage 2 the
    # objective is a weighted sum, not a chaining count.
    # >= 0.5 rather than == 1 to absorb floating-point error.
    chosen_arcs = [arc for _, arc in weighted_arcs if chosen[str(arc)].varValue >= 0.5]
    assert len(chosen_arcs) == chained, f"stage 2 returned {len(chosen_arcs)} arcs, not {chained}"
    return len(trip_ids) - len(chosen_arcs), chosen_arcs
