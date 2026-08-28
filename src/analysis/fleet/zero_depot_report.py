"""Fleet report for the no-deadheading minimum fleet (solvers/zero_depot.py)."""

from src.analysis.fleet.fleet_report import blocks_from_solution, format_blocks, format_fleet_report
from src.analysis.markdown_report import FLEET_REPORTS, write_report
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.zero_depot import arcs, fleet_size

blocks_dict = blocks_from_solution(typical_monday_trip_ids, arcs)

TITLE = "Minimum fleet with no deadheading"
SUMMARY = ("A set picks up its next trip only where it last stopped. 35 blocks, "
           "no empty running.")

if __name__ == "__main__":
    body = "\n".join([
        format_blocks(blocks_dict),
        f"\nMinimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks.\n",
        format_fleet_report(blocks_dict, "No deadheading"),
    ])
    print(f"Wrote {write_report(FLEET_REPORTS / 'zero_depot.md', TITLE, SUMMARY, 'src.analysis.fleet.zero_depot_report', body)}")
