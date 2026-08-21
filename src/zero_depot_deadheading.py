"""
Exact same code as zero_depot.py, except the valid arcs have changed to allow deadheading.
Changes the objective slightly, as to penalize long deadheading trips.
"""

from preformulation import typical_monday_deadhead_times, valid_arcs_deadheading
from typical_monday_trips import typical_monday_trip_ids, typical_monday_trip_schedule, stops
import pulp

prob = pulp.LpProblem("fleet_min", pulp.LpMaximize)

typical_monday_trip_ids_str = [str(trip) for trip in typical_monday_trip_ids]
valid_arc_str = [str(arc) for arc in valid_arcs_deadheading]
valid_arc_lookup = frozenset(valid_arcs_deadheading)

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

# We introduce a weighting system for a chaining of trips, based on the length of the 
# deadheading move. 
#
# ALPHA, BETA are fixed ratios quantifying 
ALPHA, BETA = CHOOSE CONSTANTS   # 1 move = 0.3 sets;  1 empty hour = 0.075 sets
                           # => fixed charge equals 4 h of running (crew guarantee)
                           # => 13.3 empty hours would cost you a trainset

def deadhead_penalty(arc) -> float:
    """Cost of an arc in trainsets. Zero for same-station turns."""
    end = typical_monday_trip_schedule[arc[0]][1]
    start = typical_monday_trip_schedule[arc[1]][0]
    if end == start:
        return 0.0
    hours = typical_monday_deadhead_times[frozenset([end, start])] / 3600
    return ALPHA + BETA * hours

prob.setObjective(pulp.lpSum((1 - deadhead_penalty(arc)) * var[str(arc)]
                             for arc in valid_arcs_deadheading))


# For every string trip_id, find all valid trips that can be chained before/after
# that particular trip. Add the variable corresponding to each chain to two
# dictionaries, allowing us to easily write constraints below.
departures, arrivals = {t: [] for t in typical_monday_trip_ids_str}, {t: [] for t in typical_monday_trip_ids_str}
for arc in valid_arc_lookup:
    departures[str(arc[0])].append( var[str(arc)] )
    arrivals[str(arc[1])].append( var[str(arc)] )

# Maximize the number of chains -> minimize the size of the fleet.
prob.setObjective(pulp.lpSum(var.values()))

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

# We maximized the total number of chainings. The  minimal fleet size should be the number 
# of total trips minus the optimal number of chainings.
fleet_size = len(typical_monday_trip_ids) - round(pulp.value(prob.objective))

# fleet_size was found to be 35 total trains, excluding DMU's running on the Arrow line.
assert(fleet_size == 31)

# Finding the actual blocks for this solution. We know the DAG formed by taking trips
# as nodes and chains as directed arcs (which is acyclic because no chain can go back
# in time) decomposes into some number of directed paths. The number of paths in some
# decomposition is precisely our minimal fleet size.
#
# What properties do these blocks have? Are they real-world feasible?

# valid_arcs represented as a dictionary, where key: value represents an arc key -> value.
# Only catches the arcs reported by the solver. Uses >= 0.5 to avoid any FPA error.
# Must be sensitive to the actual solution. 
arc_departures = {str(a): str(b) for a,b in valid_arcs_deadheading 
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
    print(f"Minimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks.", end = '\n')
    # Block length statistics and the bar chart live in zero_depot_viz.
    for block_id in sorted(block_origin_terminus.keys()):
        print(f"Block {block_id} " if block_id >= 10 else f"Block 0{block_id} ", end="")
        print(f"{block_origin_terminus[block_id]}")