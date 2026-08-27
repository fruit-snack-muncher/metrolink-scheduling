"""
A multi-depot extension of zero_depot_deadheading.py

Constructs and solves a LP, with the added condition that all trainsets must
originate from and return to its home overnight storage depot. Formulated as a 
max-cost flow problem, where the weight of each arc becomes the cost of flow 
along that arc. Along with some other simple constraints, the linear program 
maximizes flow cost (i.e. optimizes for cheap chains + deadheading moves).
"""
import pulp
from collections import defaultdict
from src.data_processing.preformulation import OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES, multi_weights_and_arcs, multi_depot_weighted_arrivals, multi_depot_weighted_departures
from src.data_processing.typical_monday_trips import typical_monday_trip_ids


prob = pulp.LpProblem("multi_depot_fleet_min", pulp.LpMaximize)

# Their namesake list, excluding weights.
multi_depot_arcs = [(depot, arc) for _, depot, arc in multi_weights_and_arcs]
multi_depot_arrivals = [arc for _, arc in multi_depot_weighted_arrivals]
multi_depot_departures = [arc for _, arc in multi_depot_weighted_departures]

# Decision variables. The first corresponds to chaining trips together; the second 
# corresponds to arcs depot->first trip; the third corresponds to arcs final trip->depot.
#
# Crucially, note there are SEPARATE variables for arcs depending on the trainset's
# home depot. This is made clear through an additional label for the depots. Considering
# only the first type of decision variable, this results in |OVERNIGHT_DEPOTS| times more
# decision variables than in the zero-depot cases -- a meaningfully larger problem.
#
# The depot variables are keyed by the WHOLE (depot, (trip,)) pair, exactly as they are
# named in multi_depot_departures / multi_depot_arrivals; every lookup below must pass
# that same pair, not just its trip half. The two helpers below are the single place
# either naming scheme is spelled out.
def chaining_name(depot, arc) -> str:
    """Name of the chaining variable for `arc`, flown by a trainset homed at `depot`."""
    return str(depot) + '_' + str(arc)

def depot_name(depot, trip) -> str:
    """Name of a depot variable, matching how multi_depot_(departures|arrivals) are keyed."""
    return str((depot, (trip,)))

arc_vars = pulp.LpVariable.dict('w', [chaining_name(depot, arc) for depot, arc in multi_depot_arcs], cat='Binary')
depot_depart_vars = pulp.LpVariable.dict('d', [str(arc) for arc in multi_depot_departures], cat='Binary')
depot_arrival_vars = pulp.LpVariable.dict('a', [str(arc) for arc in multi_depot_arrivals], cat='Binary')

# Writing the total flow cost of all three types of decision variables, as a list
# of products float*LpVariable to feed into setObjective below.
arc_flow_cost = [weight * arc_vars[chaining_name(depot, arc)] for weight, depot, arc in multi_weights_and_arcs]
depot_depart_flow_cost = [weight * depot_depart_vars[str(arc)] for weight, arc in multi_depot_weighted_departures]
depot_arrival_flow_cost = [weight * depot_arrival_vars[str(arc)] for weight, arc in multi_depot_weighted_arrivals]
total_flow_cost = arc_flow_cost + depot_depart_flow_cost + depot_arrival_flow_cost

# Setting the objective of the problem, as cost and flow.
prob.setObjective(pulp.lpSum( total_flow_cost ))


# Setting constraints for the maximum flow cost problem. Each node corresponds to a trip_id. Note
# the trip_id's are not labelled; only the arcs are.
#
# BINARY FLOW:
#  - Flow through every arc is 0 or 1. Declared directly on the variables (cat='Binary'), rather
#    than as |OVERNIGHT_DEPOTS| * |arcs| separate upper-bound rows.
# FLOW REQUIREMENT AT NODES:
#  - Each node (each trip) is the target of EXACTLY one arc. The same is true for arc sources.
#    This means each node is part of some unambiguous chain of trips. Work is required to ensure
#    these trips (1) originate and (2) terminate at a (3) fixed depot.
# FLOW CONSERVATION: 
#  - All trainsets originate from, and return to, a set of depots. No trainset materializes 
#    "out of thin air", as was true in the zero-depot cases.
# DEPOT CAPACITY:    
#  - The total number of trainsets emerging from a depot does not exceed given capacity.
# DEPOT FAITHFULNESS:
#  - The number of trainsets returning to a depot equals the number of trainsets originating from
#    it. With the other conditions, this guarantees the same trainsets that left the depot in the
#    morning return to it in the evening.
#
# Orientation of the depot variables, which the two flow blocks below depend on:
#  - a d_% variable is a depot -> first trip move, so it is flow INTO that trip node;
#  - an a_% variable is a last trip -> depot move, so it is flow OUT OF that trip node.

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
    """Every way a trainset homed at `depot` can arrive on `trip`: a chain, or the depot itself."""
    return chaining_in.get((depot, trip), []) + [depart_var[(depot, trip)]]

def departing_vars(depot, trip):
    """Every way a trainset homed at `depot` can leave `trip`: a chain, or back to the depot."""
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


# Solving. Every chain of trips begins with exactly one depot departure, so the number of
# d_% variables at 1 is the fleet size. Equivalently, len(trips) less the chaining arcs used.
prob.solve(pulp.PULP_CBC_CMD(msg=0))
status = pulp.LpStatus[prob.status]

fleet_size = round(sum(var.value() for var in depot_depart_vars.values()))
chained_arcs = [(depot, arc) for depot, arc in multi_depot_arcs
                if round(arc_vars[chaining_name(depot, arc)].value()) == 1]
depot_fleet_sizes = {depot: round(sum(var.value() for var in departs_by_depot[depot]))
                     for depot in OVERNIGHT_DEPOTS}

# The depot label is carried by the arcs, but analysis/ works on bare arcs, exactly as the
# zero-depot solvers expose them. So the label is handed over separately, as the two ends of
# each chain: which depot a trip is drawn from in the morning, and returned to at night.
arcs = [arc for _, arc in chained_arcs]
home_depots = {trip: depot for (depot, trip), var in depart_var.items() if round(var.value()) == 1}
terminal_depots = {trip: depot for (depot, trip), var in arrival_var.items() if round(var.value()) == 1}

if __name__ == "__main__":
    print(f"status: {status}")
    print(f"{fleet_size} trainsets over {len(typical_monday_trip_ids)} trips, "
          f"{len(chained_arcs)} chaining arcs used")
    for depot, capacity in zip(OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES):
        print(f"  depot {depot}: {depot_fleet_sizes[depot]:>3} of {capacity} trainsets")