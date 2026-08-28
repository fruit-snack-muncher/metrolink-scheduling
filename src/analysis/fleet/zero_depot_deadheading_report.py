"""Fleet report for the penalised deadheading fleet
(the penalised_* half of solvers/zero_depot_deadheading.py)."""

from src.analysis.fleet.fleet_report import (blocks_from_solution, deadhead_census, format_blocks,
                                       format_fleet_report, hhmmss)
from src.analysis.markdown_report import FLEET_REPORTS, write_report
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.zero_depot_deadheading import penalised_arcs, penalised_fleet_size

blocks_dict = blocks_from_solution(typical_monday_trip_ids, penalised_arcs)
deadhead_seconds = deadhead_census(blocks_dict)["total_seconds"]

# Just over 6 hours of empty running a day, against ~65 in the unpenalised control.
# This one IS safe to pin. Stage 2 minimises deadheading over the minimum-fleet
# solutions, so the total is the optimum of a well-posed problem rather than
# whichever solution the solver reached: it is the bottom of the 06:08:53-109:56:40
# range the control can land anywhere in. Only the *composition* is still free -
# two 5-deadhead solutions summing to the same total are both stage-2 optimal.
#
# One second more than the 06:08:52 the solvers used to report: that figure divided
# the arc weights back out by the penalty rate and truncated, losing a fraction of a
# second. The census sums the shortest-path times directly, in whole seconds.
assert hhmmss(deadhead_seconds) == "06:08:53"

TITLE = "Minimum fleet with deadheading, penalised"
SUMMARY = ("A set may reposition empty between trips, each arc charged for the empty run. "
           "31 blocks.")

if __name__ == "__main__":
    body = "\n".join([
        format_blocks(blocks_dict),
        f"\nMinimum fleet size: {penalised_fleet_size} trainsets over {len(blocks_dict)} blocks.\n",
        format_fleet_report(blocks_dict, "Deadheading, penalised"),
    ])
    print(f"Wrote {write_report(FLEET_REPORTS / 'zero_depot_deadheading.md', TITLE, SUMMARY, 'src.analysis.fleet.zero_depot_deadheading_report', body)}")
