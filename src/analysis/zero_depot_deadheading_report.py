"""Fleet report for the penalised deadheading fleet
(solvers/zero_depot_deadheading.py)."""

from src.analysis.fleet_report import (blocks_from_solution, deadhead_census, hhmmss,
                                       print_blocks, print_fleet_report)
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.zero_depot_deadheading import arcs, fleet_size

blocks_dict = blocks_from_solution(typical_monday_trip_ids, arcs)
deadhead_seconds = deadhead_census(blocks_dict)["total_seconds"]

# Just over 6 hours of empty running a day, against 61 in the unweighted control.
# One second more than the 06:08:52 the solvers used to report: that figure divided
# the arc weights back out by the penalty rate and truncated, losing a fraction of a
# second. The census sums the shortest-path times directly, in whole seconds.
assert hhmmss(deadhead_seconds) == "06:08:53"

if __name__ == "__main__":
    print_blocks(blocks_dict)
    print(f"\nMinimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks.\n")
    print_fleet_report(blocks_dict, "Deadheading, penalised")
