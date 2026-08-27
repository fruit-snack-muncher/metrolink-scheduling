"""
Determines the set of valid arcs (valid chaining of trips) in the zero-depot
case, where deadheading is NOT allowed (valid_arcs) and where deadheading is
allowed (valid_arcs_deadheading). Turnaround in the non-deadheading case is
assumed to be TURNAROUND seconds, or twenty minutes. Further description of 
valid trip chains is found in the comments.
"""

from pathlib import Path
import pandas as pd
import networkx as nx
from data_collection import stop_times
from typical_monday_trips import typical_monday_trip_ids, typical_monday_trip_schedule
from itertools import product, combinations

TURNAROUND = 1200

# ZERO DEPOT : NO DEADHEADING

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


# ZERO DEPOT : DEADHEADING ALLOWED.

# Determines if a pair of trips can be chained by a single locomotive.
# Inputs two trips tripA, tripB and a turnaround. Allows for deadheading
# between tripA arrival and tripB departure. The deadheading travel time
# is the shortest graph distance on an undirected weighted graph, where
# nodes are stops and edges are travel times. Travel times between conse-
# cutive stations are computed as mean times for revenue trips, using round
# to handle rounding errors.
#
# Crucially, travel times are ONLY computed along stops traversed on typical 
# Monday trips. Deadheading never occurs along stops not traversed by some
# trainset on a typical Monday.
# 
# Along with the deadheading, deadheading assumes a turnaround period of
# TURNAROUND seconds before and after the traversal time.
#

stop_times = stop_times.astype({"trip_id": 'int64', "stop_id": 'int64'})
typical_monday_stop_times = stop_times[stop_times['trip_id'].isin( [trip for trip in typical_monday_trip_ids] )]
typical_monday_stops = set( typical_monday_stop_times['stop_id'].to_list() )

typical_monday_graph = nx.Graph()
typical_monday_graph.add_nodes_from(typical_monday_stops)

typical_monday_consecutive_stops = {}

def time_to_sec(time: str) -> int:
    hours, minutes, seconds = time.split(':')
    return 3600 * int(hours) + 60 * int(minutes) + int(seconds)

# Computes stop-pair travel times on a trip-by-trip basis.
for trip in typical_monday_trip_ids:
    trip_stop_times = typical_monday_stop_times[typical_monday_stop_times['trip_id'] == int(trip)]
    # Note 'arrival_time' and 'departure_time' are always the same in stop_times.
    trip_stops, trip_times = trip_stop_times['stop_id'], trip_stop_times['arrival_time']
    num_stops = trip_stops.shape[0]

    # Uses a frozenset as the key for typical_monday_consecutive_stops, as to
    # eliminate the distinction between travelling A->B v.s. A<-B.
    for step in range(num_stops-1):
        stop_pair = frozenset( [trip_stops.iloc[step], trip_stops.iloc[step+1]] )
        first_time, second_time = trip_times.iloc[step], trip_times.iloc[step+1]
        stop_pair_time = time_to_sec(second_time) - time_to_sec(first_time)

        if not stop_pair in typical_monday_consecutive_stops.keys():
            typical_monday_consecutive_stops[stop_pair] = []
            
        typical_monday_consecutive_stops[stop_pair].append(stop_pair_time)

# Averages the travel time between pairs of stops, using round to get integers.
for pair, times in typical_monday_consecutive_stops.items():
    typical_monday_consecutive_stops[pair] = round( sum(times) / len(times) )

# Adds each stop-pair travel time to typical_monday_graph.
edges = []
for pair, time in typical_monday_consecutive_stops.items():
    edge = list(pair)
    edge.append(time)
    edges.append(edge)

typical_monday_graph.add_weighted_edges_from(edges)

# Find distances between all stop pairs, computed via Dijkstra's implemented in nx.
# The data is stored as a dictionary typical_monday_deadhead_times, with key: value
# has key as a frozenset of stop pairs, and value an integer distance (in time) between
# the stations.
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


# Prices an empty run against the trainset it saves: the marginal cost of a deadhead
# train-hour (~$665 - fuel at 3.00 gal/train-mile, plus wear and part of the crew's
# time) over the marginal cost of a trainset-day (~$4,030 - a six-unit consist over an
# FTA 39-year life, plus crew, servicing and idle fuel; revenue fuel does not belong
# here, as an extra set adds no revenue miles). Derivation, sources and the assumptions
# that are NOT sourced: trainset_value_hours_estimation.md at the repo root.
#
# The reciprocal is the break-even deadhead, ~5.9 h. Nothing here is that long - the
# worst arc is 4.32 h - so the penalty only orders solutions that chain equally many
# trips; above 0.232 it would start forbidding arcs outright.
#
# Fleet size is insensitive to the rate: anything from ~1e-7 to 0.37 gives the same 31
# trainsets over the same 5 deadheads, totalling 6.15 h. What guarantees we stayed
# below 0.37 is assert(fleet_size == 31) in zero_depot_deadheading, not the rate.
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

# The linear program maximizes the sum of w_{ij} x_{ij} over arcs i->j, with x_{ij} in
# {0, 1}. So far we hold the cost; w_{ij} is one trainset saved less that cost, and the
# subtraction below takes the difference. We subtract each of the above weights from 1
# to get our final list of weights. Same-station turns weigh exactly 1; the worst arc on
# this network is 4.32 h, so the weights span [0.265, 1] and none of them is negative -
# the penalty orders the solutions rather than forbidding any arc.

deadheading_weights = list(map(lambda x: 1-x, deadheading_weights))


# A list, not the bare zip: the consumers iterate this more than once, and a
# zip would be silently empty on the second pass.
weights_and_arcs = list(zip(deadheading_weights, valid_arcs_deadheading))

if __name__ == "__main__":
    # One line per arc, with the station the turn happens at and how long the
    # set sits there, which is what makes a chaining worth eyeballing.
    print(f"{len(valid_arcs)} valid chainings among {len(typical_monday_trip_ids)} trips")
    for tripA, tripB in valid_arcs:
        turn_stop = typical_monday_trip_schedule[tripA][1]
        layover = typical_monday_trip_schedule[tripB][2] - typical_monday_trip_schedule[tripA][3]
        print(f"{tripA} -> {tripB}   at stop {turn_stop:>3}   {layover // 60:>4} min layover")

    # And the deadheading arc set, which is the one the weights above apply to.
    print(f"\n{len(valid_arcs_deadheading)} valid chainings with deadheading allowed, "
          f"at {TRAINSET_DAYS_PER_DEADHEAD_HOUR} trainset-days per deadhead hour")