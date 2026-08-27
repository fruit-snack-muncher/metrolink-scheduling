"""Fleet report for the no-deadheading minimum fleet (solvers/zero_depot.py)."""

from src.analysis.fleet_report import blocks_from_solution, print_blocks, print_fleet_report
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.zero_depot import arcs, fleet_size

blocks_dict = blocks_from_solution(typical_monday_trip_ids, arcs)

if __name__ == "__main__":
    print_blocks(blocks_dict)
    print(f"\nMinimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks.\n")
    print_fleet_report(blocks_dict, "No deadheading")
