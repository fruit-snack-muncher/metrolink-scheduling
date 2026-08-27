"""Fleet report for the unpenalised deadheading control
(solvers/zero_depot_deadheading_UNWEIGHTED.py)."""

from src.analysis.fleet_report import (blocks_from_solution, deadhead_census, hhmmss,
                                       print_blocks, print_fleet_report)
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.zero_depot_deadheading_UNWEIGHTED import arcs, fleet_size

blocks_dict = blocks_from_solution(typical_monday_trip_ids, arcs)
deadhead_seconds = deadhead_census(blocks_dict)["total_seconds"]

# Absurdly long: over 61 hours of empty running a day for the same 31 trainsets.
# The whole case for weighting the arcs.
assert hhmmss(deadhead_seconds) == "61:16:42"

if __name__ == "__main__":
    print_blocks(blocks_dict)
    print(f"\nMinimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks.\n")
    print_fleet_report(blocks_dict, "Deadheading, unpenalised")
