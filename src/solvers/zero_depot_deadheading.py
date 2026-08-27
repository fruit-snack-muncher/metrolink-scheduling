"""
Exact same code as zero_depot.py, except the valid arcs have changed to allow deadheading.
Changes the objective slightly, as to penalize long deadheading trips. 

Offers an answer to the minimum fleet size problem, while staying sensitive to operational costs
due to deadheading.

"""

from preformulation import weights_and_arcs, TRAINSET_DAYS_PER_DEADHEAD_HOUR
from typical_monday_trips import typical_monday_trip_ids, typical_monday_trip_schedule, stops
import pulp

prob = pulp.LpProblem("fleet_min_weighted", pulp.LpMaximize)

typical_monday_trip_ids_str = [str(trip) for trip in typical_monday_trip_ids]
valid_arc_str = [str(arc) for _, arc in weights_and_arcs]
valid_arc_lookup = frozenset([arc for _, arc in weights_and_arcs])

# The relaxation has an integral solution, as the constraint matrix is totally unimodular.
# Concretely, the constraint matrix can be split into two blocks
#
# X = [ IN  ]  -> |valid_arcs| columns, 2 x |typical_monday_trip_ids| rows
#     [ OUT ]
# 
# where each column corresponds to an arc. Each column has exactly two 1's: one 1 corresponding 
# to where the arc originates, and one 1 corresponding to where the arc targets. This inter-
# pretation is made clearer by viewing the setup as a DAG, where the nodes correspond to trips
# and a valid chain of trips corresponds to a directed arc between trips.
#
# The constraint matrix is then totally unimodular, as it is a 0/1 matrix where each column has
# exactly one 1 in the first |typical_monday_trip_ids| rows, and exactly one more 1 in the second
# |typical_monday_trip_ids| rows.
var = pulp.LpVariable.dict("x", valid_arc_str, lowBound=0, cat='Continuous')

# We apply the modified objective function, weighting each variable by its weight.
prob.setObjective(pulp.lpSum(weight* var[str(arc)]
                             for weight, arc in weights_and_arcs))


# For every string trip_id, find all valid trips that can be chained before/after
# that particular trip. Add the variable corresponding to each chain to two
# dictionaries, allowing us to easily write constraints below.
departures, arrivals = {t: [] for t in typical_monday_trip_ids_str}, {t: [] for t in typical_monday_trip_ids_str}
for arc in valid_arc_lookup:
    departures[str(arc[0])].append( var[str(arc)] )
    arrivals[str(arc[1])].append( var[str(arc)] )

# There can be at most one arc going into a trip, and at most one arc going out of a trip.
# This behavior is captured by non-negativity of the variables and their integrality, which
# is guaranteed since the constraint matrix is totally unimodular.
for t in typical_monday_trip_ids_str:
    if departures[t]:
        prob.addConstraint(pulp.lpSum(departures[t]) <= 1, name = f"departing_{t}")
    if arrivals[t]:
        prob.addConstraint(pulp.lpSum(arrivals[t]) <= 1, name = f"arriving_{t}")

# Turn keepFiles on to see the solver files; they land in the working directory.
# Copies are kept for inspection: the MPS model in PuLP_solver_files/, and the
# CBC solution as src/fleet_min-pulp.sol.
prob.solve(pulp.PULP_CBC_CMD(msg=0, keepFiles=False))
assert(pulp.LpStatus[prob.status] == "Optimal")

# Every arc used chains two trips, so it removes exactly one trainset from the fleet.
# Note we count the arcs rather than reading pulp.value(prob.objective): the objective
# is the count only when every weight is 1, which the deadheading penalty breaks.
chainings = sum(1 for _, arc in weights_and_arcs if var[str(arc)].varValue >= 0.5)
fleet_size = len(typical_monday_trip_ids) - chainings

# fleet_size was found to be 31 total trains, excluding DMU's running on the Arrow line.
assert(fleet_size == 31)

# -----------------------------------------------
#
# ANALYSIS
#
# -----------------------------------------------

# Finding the actual blocks for this solution. We know the DAG formed by taking trips
# as nodes and chains as directed arcs (which is acyclic because no chain can go back
# in time) decomposes into some number of directed paths. The number of paths in some
# decomposition is precisely our minimal fleet size.
#
# What properties do these blocks have? Are they real-world feasible?

# valid_arcs represented as a dictionary, where key: value represents an arc key -> value.
# Only catches the arcs reported by the solver. Uses >= 0.5 to avoid any FPA error.
# Must be sensitive to the actual solution. 
arc_departures = {str(a): str(b) for (weight, (a,b)) in weights_and_arcs 
                  if var[f"({a}, {b})"].varValue >= 0.5}
arc_arrivals = set( arc_departures.values() ) # fast lookup

blocks = []
for t in typical_monday_trip_ids_str:
    if t not in arc_arrivals:
        block, current = [t], t
        while current in arc_departures:
            current = arc_departures[current]
            block.append(current)
        blocks.append(block)

blocks_dict = {i+1: blocks[i] for i in range(len(blocks))}

# No trainset can perform the same trip twice in a row.
for _, block in blocks_dict.items():
    for i in range(0, len(block) - 1):
        assert(block[i] != block[i+1])

# The paths partition the trips: every trip is served exactly once, by exactly one block.
assert(sum(len(block) for block in blocks) == len(typical_monday_trip_ids))

# Turns an integer number of seconds into HH:MM:SS as a string.
def str_second_time(time: int) -> str:
    minutes, seconds = divmod(time, 60)
    hours, minutes = divmod(minutes, 60)

    hours, minutes, seconds = list(map(lambda x: str(x) if x >= 10 else '0'+str(x), [hours, minutes, seconds]))
    return f"{hours}:{minutes}:{seconds}"

# What is the total deadheading time generated by this solution? Crucially, what is the
# deadheading time in comparison to the UNWEIGHTED case?
deadhead_duration = 0
deadhead_var_weights = [weight for (weight, (a,b)) in weights_and_arcs 
                  if var[f"({a}, {b})"].varValue >= 0.5]
deadhead_var_weights = [(1 - weight) / TRAINSET_DAYS_PER_DEADHEAD_HOUR for weight in deadhead_var_weights]

# Note the deadheading trips were in hours.
deadhead_duration = str_second_time( int(3600 * sum(deadhead_var_weights)) )
# Great improvement in deadhead running time over the unweighted case, at just over 6 runtime hours per day.
assert(deadhead_duration == '06:08:52')

# At what station does each block originate and terminate? How long is each block?
# block_origin_terminus is a dictionary, with pairs block_id: block info. The block info
# is stored as a SINGLE string containining origin/terminus stations, start/end times, and 
# total block span. Further discussion is found in the README file.
block_origin_terminus = {}
for block_num, block in blocks_dict.items():
    first_trip, last_trip = int(block[0]), int(block[-1])
    origin, _, start, _ = typical_monday_trip_schedule[first_trip]
    _, terminus, _, end = typical_monday_trip_schedule[last_trip]
    # Origin/terminus names, as opposed to stop_id's.
    origin = "ORIGIN: " + stops.loc[ stops.stop_id == origin, "stop_name"].values[0]
    terminus = "TERMINUS: " + stops.loc[ stops.stop_id == terminus, "stop_name"].values[0]
    # Reformat times as strings.
    start, end, span = "START: " + str_second_time(start), "END: " + str_second_time(end), "SPAN: " + str_second_time(end-start)
    block_origin_terminus[block_num] = ', '.join([origin, terminus, start, end, span])

# Pretty-printing blocks. Used in __main__.
def pretty_print_blocks(boolprint: bool):
    if boolprint:
        # Pretty-prints the blocks. 
        for block_num, block in blocks_dict.items():
            print(f"Block {block_num} " if block_num >= 10 else f"Block 0{block_num} ", end="")
            block_length = len(block)
            print(f"({block_length} total trips): ", end="")
            for idx, trip in enumerate(blocks_dict[block_num]):
                if idx < block_length -1:
                    print(f"{trip} -> ", end="")
                else:
                    print(trip)


if __name__ == "__main__":
    # Pretty-prints the blocks. To display trips, set boolprint to True.
    pretty_print_blocks(boolprint=True)
    print("")
    print(f"Minimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks.", end = '\n\n')
    # Total deadheading time.
    print("TOTAL DEADHEAD DURATION:", deadhead_duration, end = '\n\n')
    # Block length statistics and the bar chart live in zero_depot_viz.
    for block_id in sorted(block_origin_terminus.keys()):
        print(f"Block {block_id} " if block_id >= 10 else f"Block 0{block_id} ", end="")
        print(f"{block_origin_terminus[block_id]}")