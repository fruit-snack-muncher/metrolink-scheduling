"""Minimum fleet with deadheading allowed, penalised. A set may reposition
empty between trips, and each arc is weighted by one trainset saved less the
cost of the empty run, so the LP prefers the cheaper of two equally short
fleets. Reported on by analysis/zero_depot_deadheading_report.py.
"""

from src.data_processing.preformulation import weights_and_arcs
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.min_path_cover import solve

fleet_size, arcs = solve(typical_monday_trip_ids, weights_and_arcs)

# 31 trainsets - four fewer than without deadheading.
assert fleet_size == 31
