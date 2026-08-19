from pathlib import Path
import pandas as pd
from typical_monday_trips import typical_monday_trip_ids, typical_monday_trip_schedule
from itertools import product

TURNAROUND = 1200

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

if __name__ == "__main__":
    # One line per arc, with the station the turn happens at and how long the
    # set sits there, which is what makes a chaining worth eyeballing.
    print(f"{len(valid_arcs)} valid chainings among {len(typical_monday_trip_ids)} trips")
    for tripA, tripB in valid_arcs:
        turn_stop = typical_monday_trip_schedule[tripA][1]
        layover = typical_monday_trip_schedule[tripB][2] - typical_monday_trip_schedule[tripA][3]
        print(f"{tripA} -> {tripB}   at stop {turn_stop:>3}   {layover // 60:>4} min layover")