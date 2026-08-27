"""Fleet report for the unpenalised deadheading control
(the unweighted_* half of solvers/zero_depot_deadheading.py).

This variant is stage 1 on its own: it establishes the minimum fleet and stops
there, with nothing to choose between the solutions that achieve it. Its empty
running is therefore not a result but an artifact of which optimum CBC returned,
and it is asserted as a range rather than a value. See min_path_cover.
"""

from src.analysis.fleet_report import (blocks_from_solution, deadhead_census, hhmmss,
                                       print_blocks, print_fleet_report)
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.zero_depot_deadheading import unweighted_arcs, unweighted_fleet_size

blocks_dict = blocks_from_solution(typical_monday_trip_ids, unweighted_arcs)
deadhead_seconds = deadhead_census(blocks_dict)["total_seconds"]

# The optimal face, measured by minimising and maximising deadheading subject to the
# same 101 chainings: every value in here is a legal 31-trainset day. A pinned figure
# would only assert where one CBC build happened to land inside it, and fails on
# another machine. The width IS the finding - unpenalised, the empty running is
# unbounded up to 110 hours, which is the whole case for weighting the arcs.
LEAST_POSSIBLE, MOST_POSSIBLE = 22133, 395800  # 06:08:53 and 109:56:40
assert LEAST_POSSIBLE <= deadhead_seconds <= MOST_POSSIBLE, hhmmss(deadhead_seconds)

# The lower end is not reachable by accident: it is what stage 2 of the penalised
# variant returns, so anything above it is empty running the weighting would remove.
assert deadhead_seconds > LEAST_POSSIBLE

if __name__ == "__main__":
    print_blocks(blocks_dict)
    print(f"\nMinimum fleet size: {unweighted_fleet_size} trainsets over {len(blocks_dict)} blocks.\n")
    print_fleet_report(blocks_dict, "Deadheading, unpenalised")
