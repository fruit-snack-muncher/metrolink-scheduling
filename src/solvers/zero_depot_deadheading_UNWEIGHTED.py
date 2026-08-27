"""The deadheading model with the penalty removed: the same arc set, but every
arc weighs 1, so empty running is free. Insensitive to operational cost, and
kept as the control. Reported on by
analysis/zero_depot_deadheading_UNWEIGHTED_report.py.
"""

from src.data_processing.preformulation import weights_and_arcs
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.min_path_cover import solve

fleet_size, arcs = solve(typical_monday_trip_ids, [(1, arc) for _, arc in weights_and_arcs])

# Also 31, so the fleet size in zero_depot_deadheading is not an artifact of the
# weighting. What the penalty buys is visible only in the deadhead census.
assert fleet_size == 31
