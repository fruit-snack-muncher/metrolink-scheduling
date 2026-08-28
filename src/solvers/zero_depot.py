"""Minimum fleet with no deadheading: a set may only chain trips that continue
from where it stands. Every arc weighs the same, so the LP simply maximizes the
number of chainings. Reported on by analysis/fleet/zero_depot_report.py.
"""

from src.data_processing.preformulation import valid_arcs
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.min_path_cover import solve

weighted_arcs = [(1, arc) for arc in valid_arcs]

solution = solve(typical_monday_trip_ids, weighted_arcs)
fleet_size, arcs = solution.fleet_size, solution.arcs

# 35 trainsets, excluding the DMU's running on the Arrow line.
assert fleet_size == 35
