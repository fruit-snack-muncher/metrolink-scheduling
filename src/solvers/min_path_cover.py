"""The fleet-minimization LP, shared by every solver variant.

Trips are nodes and legal chainings are directed arcs; the DAG is acyclic
because no chain can go back in time. Covering the trips with as few paths as
possible is the same problem as choosing as many arcs as possible, and each
variant differs only in which arcs it offers and what it weighs them by.
"""

import pulp


def solve(trip_ids: list[int], weighted_arcs: list[tuple[float, tuple[int, int]]]) -> tuple[int, list[tuple[int, int]]]:
    """Maximum-weight path cover over the trip DAG.

    `weighted_arcs` is a list of (weight, (tripA, tripB)). Returns
    (fleet_size, chosen_arcs): each chosen arc chains two trips, so it removes
    one trainset from the fleet.
    """
    prob = pulp.LpProblem("fleet_min", pulp.LpMaximize)

    # The relaxation is integral, so continuous variables suffice. Each column of the
    # constraint matrix is one arc and holds exactly two 1's - one in the |trips| rows
    # for where the arc originates, one in the |trips| rows for where it targets - which
    # makes the matrix totally unimodular.
    var = pulp.LpVariable.dict("x", [str(arc) for _, arc in weighted_arcs],
                               lowBound=0, cat="Continuous")

    prob.setObjective(pulp.lpSum(weight * var[str(arc)] for weight, arc in weighted_arcs))

    # At most one arc into a trip and one out of it: a trainset can neither run two
    # trips at once nor be in two places. Non-negativity plus integrality does the rest.
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

    # Turn keepFiles on to see the solver files; they land in the working directory.
    prob.solve(pulp.PULP_CBC_CMD(msg=0, keepFiles=False))
    assert pulp.LpStatus[prob.status] == "Optimal"

    # Count the arcs rather than reading pulp.value(prob.objective): the objective is
    # the chaining count only when every weight is 1, which a deadhead penalty breaks.
    # >= 0.5 rather than == 1 to absorb floating-point error.
    chosen_arcs = [arc for _, arc in weighted_arcs if var[str(arc)].varValue >= 0.5]
    return len(trip_ids) - len(chosen_arcs), chosen_arcs
