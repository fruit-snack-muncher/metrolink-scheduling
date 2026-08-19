from preformulation import valid_arcs
from typical_monday_trips import typical_monday_trip_ids, typical_monday_trip_schedule
import pulp

prob = pulp.LpProblem("fleet_min", pulp.LpMaximize)

typical_monday_trip_ids_str = [str(trip) for trip in typical_monday_trip_ids]
valid_arc_str = [str(arc) for arc in valid_arcs]
valid_arc_lookup = frozenset(valid_arcs)

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

# fleet_size was found to be 38 total trains.
assert(fleet_size == 38)


# Finding the actual blocks for this solution. We know the DAG formed by taking trips
# as nodes and chains as directed arcs (which is acyclic because no chain can go back
# in time) decomposes into some number of directed paths. The number of paths in some
# decomposition is precisely our minimal fleet size.
#
# What properties do these blocks have? Are they real-world feasible?

# valid_arcs represented as a dictionary, where key: value represents an arc key -> value.
# Only catches the arcs reported by the solver. Uses >= 0.5 to avoid any FPA error.
# Must be sensitive to the actual solution. 
arc_departures = {str(a): str(b) for a,b in valid_arcs 
                  if var[f"({a}, {b})"].varValue >= 0.5}
arc_arrivals = set( arc_departures.values() ) # fast lookup

blocks = []
for t in typical_monday_trip_ids_str:
    if t not in arc_arrivals:
        block, current = [t], t
        while current in arc_departures:
            block.append(current)
            current = arc_departures[current]
        blocks.append(block)

blocks_dict = {i+1: blocks[i] for i in range(len(blocks))}

if __name__ == "__main__":
    # Pretty-prints the blocks.
    for block_num, block in blocks_dict.items():
        print(f"Block {block_num}: " if block_num >= 10 else f"Block 0{block_num}: ", end="")
        block_length = len(block)
        for idx, trip in enumerate(blocks_dict[block_num]):
            if idx < block_length -1:
                print(f"{trip} -> ", end="")
            else:
                print(trip)