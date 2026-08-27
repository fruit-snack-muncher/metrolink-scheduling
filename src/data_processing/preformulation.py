"""
Determines the set of valid arcs (valid chaining of trips) in the zero-depot
case, where deadheading is NOT allowed (valid_arcs) and where deadheading is
allowed (valid_arcs_deadheading). Turnaround in the non-deadheading case is
assumed to be TURNAROUND seconds, or twenty minutes. Further description of 
valid trip chains is found in the comments.
"""

import networkx as nx
from src.data_processing.data_collection import stop_times
from src.data_processing.typical_monday_trips import typical_monday_trip_ids, typical_monday_trip_schedule
from itertools import product, combinations

TURNAROUND = 1200


# ==============================================================================
#
# ZERO DEPOT : NO DEADHEADING ALLOWED.
#
# ==============================================================================

# Determines if a pair of trips can be chained by a single locomotive.
# Inputs two trips tripA, tripB and a turnaround. Requires that tripA
# ends at the station where tripB begins, and the delay between A 
# arrival and B departure be at least `turnaround` seconds, which defaults
# to 1200 seconds -> 20 minutes.
#
# Remember that trip data, as stored in typical_monday_trip_schedule,
# is stored as a tuple for each trip_id:
#   departure stop_id, arrival stop_id, departure time, arrival time.
def valid_pair(tripA, tripB, turnaround=TURNAROUND) -> bool: #1200 s = 20 min
    tripA_schedule, tripB_schedule = typical_monday_trip_schedule[tripA], typical_monday_trip_schedule[tripB]
    return (tripA_schedule[1] == tripB_schedule[0]) and (tripA_schedule[3] + turnaround <= tripB_schedule[2])

# All valid arcs; i.e. all valid subsequent trips trip A -> trip B.
# Will remain the set of valid directed arcs in constructing a DAG for the
# setup of the linear program.
valid_arcs = product(typical_monday_trip_ids, repeat=2)
valid_arcs = [arc for arc in valid_arcs if valid_pair(arc[0], arc[1])]


# ==============================================================================
#
# ZERO DEPOT : DEADHEADING ALLOWED.
#
# ==============================================================================

# Chaining as in valid_pair, but a deadhead run is allowed between tripA
# arrival and tripB departure. Its time is the shortest path on an undirected
# graph of stops, edges weighted by mean consecutive-stop revenue times.
# Only stops served on a typical Monday are usable; deadheading never runs
# elsewhere. A TURNAROUND applies both before and after the deadhead run.

stop_times = stop_times.astype({"trip_id": 'int64', "stop_id": 'int64'})
typical_monday_stop_times = stop_times[stop_times['trip_id'].isin( [trip for trip in typical_monday_trip_ids] )]
typical_monday_stops = set( typical_monday_stop_times['stop_id'].to_list() )

typical_monday_graph = nx.Graph()
typical_monday_graph.add_nodes_from(typical_monday_stops)

typical_monday_consecutive_stops = {}

def time_to_sec(time: str) -> int:
    hours, minutes, seconds = time.split(':')
    return 3600 * int(hours) + 60 * int(minutes) + int(seconds)

# Stop-pair travel times, trip by trip.
for trip in typical_monday_trip_ids:
    trip_stop_times = typical_monday_stop_times[typical_monday_stop_times['trip_id'] == int(trip)]
    # Note 'arrival_time' and 'departure_time' are always the same in stop_times.
    trip_stops, trip_times = trip_stop_times['stop_id'], trip_stop_times['arrival_time']
    num_stops = trip_stops.shape[0]

    # Frozenset key: A->B and A<-B are the same pair.
    for step in range(num_stops-1):
        stop_pair = frozenset( [trip_stops.iloc[step], trip_stops.iloc[step+1]] )
        first_time, second_time = trip_times.iloc[step], trip_times.iloc[step+1]
        stop_pair_time = time_to_sec(second_time) - time_to_sec(first_time)

        if not stop_pair in typical_monday_consecutive_stops.keys():
            typical_monday_consecutive_stops[stop_pair] = []
            
        typical_monday_consecutive_stops[stop_pair].append(stop_pair_time)

# Mean travel time per stop pair, rounded to an integer.
for pair, times in typical_monday_consecutive_stops.items():
    typical_monday_consecutive_stops[pair] = round( sum(times) / len(times) )

# Adds each stop-pair travel time to typical_monday_graph.
edges = []
for pair, time in typical_monday_consecutive_stops.items():
    edge = list(pair)
    edge.append(time)
    edges.append(edge)

typical_monday_graph.add_weighted_edges_from(edges)

# All-pairs distances via Dijkstra, keyed by frozenset of the stop pair.
typical_monday_stop_combinations = list(combinations(typical_monday_stops, 2))
typical_monday_deadhead_times = {}
for origin, terminus in typical_monday_stop_combinations:
    key = frozenset([origin, terminus])
    try:
        typical_monday_deadhead_times[key] = nx.shortest_path_length(typical_monday_graph, origin, terminus, weight='weight')
    except nx.NetworkXNoPath:
        typical_monday_deadhead_times[key] = float('inf') # No path exists between a pair of stations.

def valid_pair_deadheading(tripA, tripB, turnaround=TURNAROUND):
    tripA_schedule, tripB_schedule = typical_monday_trip_schedule[tripA], typical_monday_trip_schedule[tripB]
    _, departure, _, departure_time = tripA_schedule
    arrival, _, arrival_time, _ = tripB_schedule

    if departure == arrival:
        return valid_pair(tripA, tripB, turnaround)
    else:
        key = frozenset([departure, arrival])
        deadheading = typical_monday_deadhead_times[key]
        return departure_time + turnaround + deadheading + turnaround <= arrival_time

valid_arcs_deadheading = product(typical_monday_trip_ids, repeat=2)
valid_arcs_deadheading = [arc for arc in valid_arcs_deadheading if valid_pair_deadheading(arc[0], arc[1])]


# Prices an empty run against the trainset it saves: ~$665 per deadhead train-hour over
# ~$4,030 per trainset-day. Derivation and sources: trainset_value_hours_estimation.md.
#
# Break-even is the reciprocal, ~5.9 h; the worst arc here is 4.32 h, so the penalty only
# orders solutions rather than forbidding arcs. Fleet size is insensitive to the rate -
# ~1e-7 to 0.37 all give 31 trainsets over the same 5 deadheads (6.15 h). The guard on
# staying under 0.37 is assert(fleet_size == 31) in zero_depot_deadheading, not the rate.
TRAINSET_DAYS_PER_DEADHEAD_HOUR = 0.17

deadheading_weights = []
for tripA, tripB in valid_arcs_deadheading:
    _, arrival, _, _ = typical_monday_trip_schedule[tripA]
    departure, _, _, _ = typical_monday_trip_schedule[tripB]
    if arrival == departure:
        deadheading_weights.append(0)
    else:
        deadheading_weights.append( typical_monday_deadhead_times[frozenset([arrival, departure])]
                                    / 3600 * TRAINSET_DAYS_PER_DEADHEAD_HOUR )

# The LP maximizes sum of w_{ij} x_{ij}, so w_{ij} is one trainset saved less the cost
# above. Weights span [0.265, 1] - same-station turns are exactly 1, none is negative.
modified_deadheading_weights = list(map(lambda x: 1-x, deadheading_weights))

# A list, not the bare zip: consumers iterate this more than once.
weights_and_arcs = list(zip(modified_deadheading_weights, valid_arcs_deadheading))


# ==============================================================================
#
# MULTI-DEPOT : DEADHEADING ALLOWED.
#
# ==============================================================================

# Adds additional weights for deadheading trips to and from various stops associated with
# overnight storage facilities. Crucially, every trainset must originate from and return
# to a particular home depot. 
# 
# As a linear program, there is now an additional sort of decision variable, corresponding 
# to the choice of home depot. Naturally, we re-formulate the problem through MAX-cost flow,
# where the cost of sending flow along an arc is equal to the weight of the arc. Notably, the
# cost of flow for a same-stop trip chain is 1.
#
# As determining the home depot (source) to initiate a chain of trips also determines the 
# home depot for chain termination, the only decision is where a chain of trips originates.
# We interpret a deadheading move to/from an overnight depot as pure cost, so we drop + 1 
# from the original weighting system.
#
# Stops associated/in near proximity with overnight storage depots.
# 107 : L.A. Union Station, Central Maintenance Facility (30+ trainset capacity), as per
#       (https://metrolinktrains.com/community-main/cmf/). Assumed 25, as per claim that
#       25 trainsets are maintained daily at CMF.
# 185 : San Bernardino Downtown, Eastern Maintenance Facility (7 trainset capacity)
# TO BE UPDATED!

OVERNIGHT_DEPOTS = [107, 185]
OVERNIGHT_CAPACITIES = [30, 7]

# All deadheading times to overnight depots, collected for every stop-depot pair.
# The deadheading times are pre-emptively weighted.
multi_depot_deadheading = {}
multi_depot_stops = list(product(typical_monday_stops, OVERNIGHT_DEPOTS))
for stop, depot in multi_depot_stops:
    key = (stop, depot)
    if stop == depot:
        # A trainset already at its depot runs no empty miles, so no penalty.
        multi_depot_deadheading[key] = 0
    else:
        deadhead_time = typical_monday_deadhead_times[frozenset(key)]
        # A depot on a branch disconnected from some stop would put -inf coefficients in the
        # objective. Both current depots reach every Monday stop; fail loudly if that changes.
        assert deadhead_time != float('inf'), f"stop {stop} is unreachable from depot {depot}"
        multi_depot_deadheading[key] = 0 - (deadhead_time / 3600 * TRAINSET_DAYS_PER_DEADHEAD_HOUR)

# The deadhead weights for:
#  1. Departing from a depot to initiate a trip, and
#  2. Arriving at a depot to conclude a day's chain.
# For every trip, finds the deadhead weight for each depot->trip and trip-> 
multi_depot_weighted_departures, multi_depot_weighted_arrivals = {}, {}
for trip in typical_monday_trip_ids:
    trip_stop_times = typical_monday_stop_times[typical_monday_stop_times['trip_id'] == int(trip)]
    origin, terminus = trip_stop_times.iloc[0, 3], trip_stop_times.iloc[-1, 3]
    for depot in OVERNIGHT_DEPOTS:
        multi_depot_weighted_departures[(depot, (trip,))] = multi_depot_deadheading[(origin, depot)]
        multi_depot_weighted_arrivals[(depot, (trip,))] = multi_depot_deadheading[(terminus, depot)]

for _, (trip,) in multi_depot_weighted_departures.keys():
    assert(trip in typical_monday_trip_ids)
for _, (trip,) in multi_depot_weighted_arrivals.keys():
    assert(trip in typical_monday_trip_ids)

# Change to list[float, tuple[int, tuple[int]]].
multi_depot_weighted_departures = [(weight, departure) for departure, weight in multi_depot_weighted_departures.items()]
multi_depot_weighted_arrivals = [(weight, arrival) for arrival, weight in multi_depot_weighted_arrivals.items()]

# A modified version of weights_and_arcs, where the arc names includes the home depot for each
# chained trip not involving a deadhead move to/away from a depot.
multi_weights_and_arcs = [(weight, depot, arc) for depot in OVERNIGHT_DEPOTS
                                               for weight, arc in weights_and_arcs]

if __name__ == "__main__":
    # One line per arc: where the turn happens and how long the set sits there.
    print(f"{len(valid_arcs)} valid chainings among {len(typical_monday_trip_ids)} trips")
    for tripA, tripB in valid_arcs:
        turn_stop = typical_monday_trip_schedule[tripA][1]
        layover = typical_monday_trip_schedule[tripB][2] - typical_monday_trip_schedule[tripA][3]
        print(f"{tripA} -> {tripB}   at stop {turn_stop:>3}   {layover // 60:>4} min layover")

    # The deadheading arc set, which the weights above apply to.
    print(f"\n{len(valid_arcs_deadheading)} valid chainings with deadheading allowed, "
          f"at {TRAINSET_DAYS_PER_DEADHEAD_HOUR} trainset-days per deadhead hour")