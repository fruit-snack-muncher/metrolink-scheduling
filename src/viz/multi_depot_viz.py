"""Block length distribution for the multi-depot fleet, partitioned by home depot.

The counterpart to zero_depot_deadheading_viz. Every set now belongs to an
overnight depot and must be back there by the end of the day, so the interesting
question is no longer only how long the blocks are but how the work divides
between the facilities: whether one depot carries the long duties while the other
turns stubs, or whether the two look alike.

The bars are therefore laid out one depot at a time, coloured per depot, while the
mean, median and Tukey fences stay fleet-wide - each depot is read against the
whole distribution rather than against itself.

The blocks come from multi_depot_report; importing it runs the LP solve once, and
nothing here re-derives them. The statistics and the chart live in block_lengths,
shared with the zero-depot variants.
"""

from src.analysis.fleet.fleet_report import stop_name
from src.analysis.fleet.multi_depot_report import blocks_dict, depot_of_block
from src.data_processing.preformulation import OVERNIGHT_DEPOTS
from src.viz.block_lengths import FIGURES, plot_block_lengths, print_block_length_stats

PATH = FIGURES / "block_lengths_multi_depot.png"
HEADING = "Block lengths, multi-depot"
TITLE = "Trips per block, by home depot"
SUBTITLE = "Minimum fleet with every set home overnight, typical Monday"


def depot_label(depot: int) -> str:
    """Names a depot band on the chart: the stop it sits at, not its GTFS id."""
    return f"{stop_name(depot)} ({depot})"


if __name__ == "__main__":
    print_block_length_stats(blocks_dict, HEADING)
    print()
    for depot in OVERNIGHT_DEPOTS:
        depot_blocks = {n: b for n, b in blocks_dict.items() if depot_of_block[n] == depot}
        print_block_length_stats(depot_blocks, f"  {depot_label(depot)}")
        print()
    print(f"Wrote bar chart to {plot_block_lengths(blocks_dict, PATH, TITLE, SUBTITLE, groups=depot_of_block, group_order=OVERNIGHT_DEPOTS, group_label=depot_label)}")
