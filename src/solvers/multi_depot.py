"""
A multi-depot extension of zero_depot_deadheading.py

Constructs and solves a LP, with the added condition that all trainsets must
originate from and return to its home overnight storage depot. Formulated as a
max-cost flow problem, where the weight of each arc becomes the cost of flow
along that arc. Along with some other simple constraints, the linear program
maximizes flow cost (i.e. optimizes for cheap chains + deadheading moves).

Solved in TWO STAGES, for the reason min_path_cover is. Stage 1 maximizes the
bare chaining count, which is what the fleet size measures; stage 2 then
maximizes flow cost *subject to that count*, choosing among the minimum-fleet
solutions rather than trading a trainset against the cost of positioning it. A
single blended objective cannot promise the fleet size it reports: one chaining
fewer, with enough empty running saved, scores identically and comes back as a
larger fleet.

Unlike min_path_cover, BOTH stages here declare integer variables. There, stage 1
may relax to Continuous because every column holds exactly two 1's - one departing
row, one arriving row - which makes the matrix totally unimodular and its
relaxation integral. No such structure survives here: a chaining variable appears
in four rows with mixed signs, the two flow-requirement rows for the trips it
joins and the two per-depot flow-conservation rows, where it enters +1 at one end
and -1 at the other, and the depot-capacity rows add more besides. With no TU
argument to lean on, integrality has to be declared and branched on.

Any of the three variable families - chainings, depot departures, depot arrivals -
can be pinned at 0 or 1 through `solve`, which is what the sensitivity study in
analysis/forcing/forcing_sweep.py runs on: mandate or forbid one move, re-solve, and see
whether the minimum fleet and the flow-cost optimum survive it. Forcing can make
the problem infeasible, so `solve` returns a status rather than asserting one. The
module-level names below are the UNFORCED baseline, solved once at import, and are
what analysis/ reads.
"""
import pulp
from collections import defaultdict
from typing import NamedTuple
from src.data_processing.preformulation import OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES, multi_weights_and_arcs, multi_depot_weighted_arrivals, multi_depot_weighted_departures
from src.data_processing.typical_monday_trips import typical_monday_trip_ids


# Their namesake list, excluding weights.
multi_depot_arcs = [(depot, arc) for _, depot, arc in multi_weights_and_arcs]
multi_depot_arrivals = [arc for _, arc in multi_depot_weighted_arrivals]
multi_depot_departures = [arc for _, arc in multi_depot_weighted_departures]

# The decision variables are named, not indexed, so the two naming schemes live here -
# the single place either is spelled out, shared by both stages and by the result
# extraction at the bottom.
#
# The depot variables are keyed by the WHOLE (depot, (trip,)) pair, exactly as they are
# named in multi_depot_departures / multi_depot_arrivals; every lookup must pass that
# same pair, not just its trip half.
def chaining_name(depot, arc) -> str:
    """Name of the chaining variable for `arc`, flown by a trainset homed at `depot`."""
    return str(depot) + '_' + str(arc)

def depot_name(depot, trip) -> str:
    """Name of a depot variable, matching how multi_depot_(departures|arrivals) are keyed."""
    return str((depot, (trip,)))


class Model(NamedTuple):
    """One built multi-depot problem: every constraint, and both candidate objectives.

    The objectives are handed back unset. Which one is imposed - and whether the
    chaining count is pinned first - is what separates the two stages.
    """
    prob: pulp.LpProblem
    arc_vars: dict
    depart_var: dict          # (depot, trip) -> the depot -> first trip variable
    arrival_var: dict         # (depot, trip) -> the last trip -> depot variable
    departs_by_depot: dict
    chaining_count: pulp.LpAffineExpression   # stage 1's objective
    flow_cost: pulp.LpAffineExpression        # stage 2's objective


class Solution(NamedTuple):
    """What one (possibly forced) run of `solve` found.

    Everything but `status` is None when the forcing made the problem infeasible.
    `chained` and `objective` are what the sweep compares against an unforced
    baseline: the first says whether the minimum fleet is still reachable, the
    second whether the flow-cost optimum is.
    """
    status: str                              # a pulp.LpStatus string
    fleet_size: int | None
    chained: int | None                      # stage 1's optimum: chainings used
    objective: float | None                  # stage 2's flow cost, at the returned solution
    arcs: list[tuple[int, int]] | None       # bare arcs, as the zero-depot solvers expose them
    chained_arcs: list[tuple[int, tuple[int, int]]] | None   # the same arcs, depot-labelled
    home_depots: dict[int, int] | None       # trip -> depot it is drawn from in the morning
    terminal_depots: dict[int, int] | None   # trip -> depot it is returned to at night
    depot_fleet_sizes: dict[int, int] | None


def build_model(name: str,
                forced_chainings: dict[tuple[int, tuple[int, int]], int] | None = None,
                forced_departures: dict[tuple[int, int], int] | None = None,
                forced_arrivals: dict[tuple[int, int], int] | None = None) -> Model:
    """The whole feasible region, built fresh so the two stages cannot share state.

    The three `forced_%` maps pin variables at 0 or 1, keyed exactly as the three
    families are elsewhere in this module: (depot, arc) for a chaining, (depot, trip)
    for a departure or an arrival.

    Each node corresponds to a trip_id. Note the trip_id's are not labelled; only the
    arcs are.

    BINARY FLOW:
     - Flow through every arc is 0 or 1. Declared directly on the variables, rather than
       as |OVERNIGHT_DEPOTS| * |arcs| separate upper-bound rows.
    FLOW REQUIREMENT AT NODES:
     - Each node (each trip) is the target of EXACTLY one arc. The same is true for arc
       sources. This means each node is part of some unambiguous chain of trips. Work is
       required to ensure these trips (1) originate and (2) terminate at a (3) fixed depot.
    FLOW CONSERVATION:
     - All trainsets originate from, and return to, a set of depots. No trainset
       materializes "out of thin air", as was true in the zero-depot cases.
    DEPOT CAPACITY:
     - The total number of trainsets emerging from a depot does not exceed given capacity.
    DEPOT FAITHFULNESS:
     - The number of trainsets returning to a depot equals the number of trainsets
       originating from it. With the other conditions, this guarantees the same trainsets
       that left the depot in the morning return to it in the evening.

    Orientation of the depot variables, which the two flow blocks depend on:
     - a d_% variable is a depot -> first trip move, so it is flow INTO that trip node;
     - an a_% variable is a last trip -> depot move, so it is flow OUT OF that trip node.
    """
    prob = pulp.LpProblem(name, pulp.LpMaximize)

    # Decision variables. The first corresponds to chaining trips together; the second
    # corresponds to arcs depot->first trip; the third corresponds to arcs final trip->depot.
    #
    # Crucially, note there are SEPARATE variables for arcs depending on the trainset's
    # home depot. This is made clear through an additional label for the depots. Considering
    # only the first type of decision variable, this results in |OVERNIGHT_DEPOTS| times more
    # decision variables than in the zero-depot cases -- a meaningfully larger problem.
    arc_vars = pulp.LpVariable.dict('w', [chaining_name(depot, arc) for depot, arc in multi_depot_arcs], cat='Binary')
    depot_depart_vars = pulp.LpVariable.dict('d', [str(arc) for arc in multi_depot_departures], cat='Binary')
    depot_arrival_vars = pulp.LpVariable.dict('a', [str(arc) for arc in multi_depot_arrivals], cat='Binary')

    # Forced variables are pinned by their BOUNDS rather than by an added row. Both stages
    # branch here anyway, so nothing is being protected the way min_path_cover's stage 1 is;
    # bounds are simply what a fixed variable is, and CBC presolves them away rather than
    # carrying |forced| extra rows. A KeyError is the right failure - a key naming no
    # variable would otherwise be a forcing silently never applied.
    for (depot, arc), value in (forced_chainings or {}).items():
        pinned = arc_vars[chaining_name(depot, arc)]
        pinned.lowBound = pinned.upBound = value
    for (depot, trip), value in (forced_departures or {}).items():
        pinned = depot_depart_vars[depot_name(depot, trip)]
        pinned.lowBound = pinned.upBound = value
    for (depot, trip), value in (forced_arrivals or {}).items():
        pinned = depot_arrival_vars[depot_name(depot, trip)]
        pinned.lowBound = pinned.upBound = value

    # Every constraint below asks the same two questions of a (depot, trip) pair: what can put a
    # trainset onto this trip, and what can take it off. Answering by filtering the arc lists costs
    # a full rescan per pair -- |OVERNIGHT_DEPOTS| * |trips| passes over |OVERNIGHT_DEPOTS| * |arcs|
    # entries. Instead the lists are bucketed once, here, and the blocks below are dict lookups.
    chaining_in, chaining_out = defaultdict(list), defaultdict(list)
    for depot, arc in multi_depot_arcs:
        var = arc_vars[chaining_name(depot, arc)]
        chaining_in[(depot, arc[1])].append(var)
        chaining_out[(depot, arc[0])].append(var)

    # Preformulation emits exactly one departure and one arrival per (depot, trip), so unlike the
    # chaining buckets these hold a single variable each.
    depart_var = {(depot, trip): depot_depart_vars[depot_name(depot, trip)]
                  for depot, (trip,) in multi_depot_departures}
    arrival_var = {(depot, trip): depot_arrival_vars[depot_name(depot, trip)]
                   for depot, (trip,) in multi_depot_arrivals}

    def arriving_vars(depot, trip):
        """Every way a trainset homed at `depot` can arrive on `trip`: a chain, or the depot itself.
        No such way might exist, justifying the use of .get()"""
        return chaining_in.get((depot, trip), []) + [depart_var[(depot, trip)]]

    def departing_vars(depot, trip):
        """Every way a trainset homed at `depot` can leave `trip`: a chain, or back to the depot.
        No such way might exist, justifying the use of .get()"""
        return chaining_out.get((depot, trip), []) + [arrival_var[(depot, trip)]]

    # Per-depot totals, for the two aggregate blocks at the end.
    departs_by_depot = {depot: [depart_var[(depot, trip)] for trip in typical_monday_trip_ids]
                        for depot in OVERNIGHT_DEPOTS}
    arrivals_by_depot = {depot: [arrival_var[(depot, trip)] for trip in typical_monday_trip_ids]
                         for depot in OVERNIGHT_DEPOTS}

    # FLOW REQUIREMENT AT NODES:
    for trip in typical_monday_trip_ids:
        arriving = [var for depot in OVERNIGHT_DEPOTS for var in arriving_vars(depot, trip)]
        departing = [var for depot in OVERNIGHT_DEPOTS for var in departing_vars(depot, trip)]

        prob.addConstraint(pulp.lpSum(arriving) == 1, name=f'flow_requirement_arrival_{trip}')
        prob.addConstraint(pulp.lpSum(departing) == 1, name=f'flow_requirement_departing_{trip}')

    # FLOW CONSERVATION:
    #
    # For each node, for a fixed depot, the flow of depot-labelled arcs in and out of the node must
    # equal zero. Along with the flow requirement constraint, this places each node along a chain
    # of arcs with a FIXED DEPOT.
    #
    # Flow always propagates away from (source) depot nodes, and disappears in (sink) depot nodes.
    # The idea is captured by the way we formulated our variables; all d_% variables correspond
    # to trip chains beginning from a (source) depot node, and all a_% variables correspond to trip
    # chains ending at a (sink) depot node.
    for depot in OVERNIGHT_DEPOTS:
        for trip in typical_monday_trip_ids:
            prob.addConstraint(pulp.lpSum(arriving_vars(depot, trip)) - pulp.lpSum(departing_vars(depot, trip)) == 0,
                               name=f'flow_conservation_{depot}_{trip}')

    # DEPOT CAPACITY:
    for depot, capacity in zip(OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES):
        prob.addConstraint(pulp.lpSum(departs_by_depot[depot]) <= capacity, name=f'depot_capacity_{depot}')

    # DEPOT FAITHFULNESS:
    #
    # Implied by the two blocks above: the flow requirement gives each trip exactly one unit of
    # inflow, so exactly one depot label is active at that node, and per-depot conservation carries
    # that same label along the whole chain. Kept as a cheap, redundant guard on the formulation.
    for depot in OVERNIGHT_DEPOTS:
        prob.addConstraint(pulp.lpSum(departs_by_depot[depot]) - pulp.lpSum(arrivals_by_depot[depot]) == 0,
                           name=f'depot_faithfulness_{depot}')

    # The two objectives, built but not imposed. The flow cost is the total over all three
    # kinds of decision variable; the chaining count ignores the weights entirely.
    arc_flow_cost = [weight * arc_vars[chaining_name(depot, arc)] for weight, depot, arc in multi_weights_and_arcs]
    depot_depart_flow_cost = [weight * depot_depart_vars[str(arc)] for weight, arc in multi_depot_weighted_departures]
    depot_arrival_flow_cost = [weight * depot_arrival_vars[str(arc)] for weight, arc in multi_depot_weighted_arrivals]

    return Model(prob=prob,
                 arc_vars=arc_vars,
                 depart_var=depart_var,
                 arrival_var=arrival_var,
                 departs_by_depot=departs_by_depot,
                 chaining_count=pulp.lpSum(arc_vars.values()),
                 flow_cost=pulp.lpSum(arc_flow_cost + depot_depart_flow_cost + depot_arrival_flow_cost))



def solve(forced_chainings: dict[tuple[int, tuple[int, int]], int] | None = None,
          forced_departures: dict[tuple[int, int], int] | None = None,
          forced_arrivals: dict[tuple[int, int], int] | None = None) -> Solution:
    """Both stages, over a feasible region narrowed by whatever is forced.

    The three `forced_%` maps are passed straight to `build_model`, and to BOTH stages -
    a forcing stage 1 respected but stage 2 did not would pin the fleet at a count stage 2
    is not solving for.
    """
    forcing = (forced_chainings, forced_departures, forced_arrivals)

    # STAGE 1: the fleet size itself. Chains partition the trips, so the number of chains is
    # len(trips) less the chainings used - maximizing chainings is minimizing the fleet, and
    # unlike the flow cost it cannot be talked out of a trainset by a cheaper deadhead.
    stage1 = build_model("multi_depot_fleet_min", *forcing)
    stage1.prob.setObjective(stage1.chaining_count)
    stage1.prob.solve(pulp.PULP_CBC_CMD(msg=0))
    # Unforced this is always Optimal. A forcing can genuinely contradict the flow rows -
    # two depots both mandated to open the same trip, say - and that is a finding to report,
    # not a bug to assert on.
    if pulp.LpStatus[stage1.prob.status] != "Optimal":
        return Solution(pulp.LpStatus[stage1.prob.status], *[None] * 8)
    chained = round(pulp.value(stage1.prob.objective))

    # STAGE 2: among the solutions achieving that fleet, the cheapest to chain and position.
    # An exact equality, not a bound: the variables are integral, so no tolerance is needed to
    # survive floating-point, and slack here is exactly what would let stage 2 buy its weights
    # back with a trainset.
    stage2 = build_model("multi_depot_fleet_min_weighted", *forcing)
    stage2.prob.addConstraint(stage2.chaining_count == chained, name='minimum_fleet')
    stage2.prob.setObjective(stage2.flow_cost)
    stage2.prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[stage2.prob.status]
    # Stage 1's own solution satisfies every row here, so infeasibility would mean the two
    # stages disagree about the feasible region. Still returned rather than asserted, so one
    # bad point cannot take a whole sweep down.
    if status != "Optimal":
        return Solution(status, *[None] * 8)

    # Every chain of trips begins with exactly one depot departure, so the number of d_%
    # variables at 1 is the fleet size.
    fleet_size = round(sum(var.value() for var in stage2.depart_var.values()))
    chained_arcs = [(depot, arc) for depot, arc in multi_depot_arcs
                    if round(stage2.arc_vars[chaining_name(depot, arc)].value()) == 1]
    depot_fleet_sizes = {depot: round(sum(var.value() for var in stage2.departs_by_depot[depot]))
                         for depot in OVERNIGHT_DEPOTS}

    # The two ways of counting a fleet have to agree: one departure opens each chain, and the
    # chains partition the trips. True under any forcing, so these stay here; the assertion
    # that the answer is 31 belongs to the unforced baseline alone, and lives below.
    assert fleet_size == len(typical_monday_trip_ids) - chained
    assert len(chained_arcs) == chained

    # The depot label is carried by the arcs, but analysis/ works on bare arcs, exactly as the
    # zero-depot solvers expose them. So the label is handed over separately, as the two ends of
    # each chain: which depot a trip is drawn from in the morning, and returned to at night.
    arcs = [arc for _, arc in chained_arcs]
    home_depots = {trip: depot for (depot, trip), var in stage2.depart_var.items() if round(var.value()) == 1}
    terminal_depots = {trip: depot for (depot, trip), var in stage2.arrival_var.items() if round(var.value()) == 1}

    return Solution(status=status,
                    fleet_size=fleet_size,
                    chained=chained,
                    objective=pulp.value(stage2.prob.objective),
                    arcs=arcs,
                    chained_arcs=chained_arcs,
                    home_depots=home_depots,
                    terminal_depots=terminal_depots,
                    depot_fleet_sizes=depot_fleet_sizes)


# The UNFORCED baseline, solved once at import. analysis/ reads these names, and the sweep
# in analysis/forcing/forcing_sweep.py compares every forced run against this one.
baseline = solve()
status = baseline.status
fleet_size, chained = baseline.fleet_size, baseline.chained
arcs, chained_arcs = baseline.arcs, baseline.chained_arcs
home_depots, terminal_depots = baseline.home_depots, baseline.terminal_depots
depot_fleet_sizes = baseline.depot_fleet_sizes

assert fleet_size == 31

if __name__ == "__main__":
    print(f"status: {status}")
    print(f"{fleet_size} trainsets over {len(typical_monday_trip_ids)} trips, "
          f"{len(chained_arcs)} chaining arcs used")
    for depot, capacity in zip(OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES):
        print(f"  depot {depot}: {depot_fleet_sizes[depot]:>3} of {capacity} trainsets")
