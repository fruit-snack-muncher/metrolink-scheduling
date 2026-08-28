"""Block length distribution for the minimum fleet with deadheading allowed.

The counterpart to zero_depot_viz. A set may now reposition empty between two
trips, so a block no longer has to stay where it last stopped. The question the
distribution answers is whether the four trainsets deadheading saves come from
spreading work more evenly or from a handful of blocks absorbing everything.

The blocks themselves come from zero_depot_deadheading_report; importing it runs
the LP solve once, and nothing here re-derives them. The statistics and the
chart live in block_lengths, shared with the zero-depot variant.
"""

from src.analysis.fleet.zero_depot_deadheading_report import blocks_dict
from src.viz.block_lengths import FIGURES, plot_block_lengths, print_block_length_stats

PATH = FIGURES / "block_lengths_deadheading.png"
HEADING = "Block lengths, deadheading allowed"
TITLE = "Trips per block, deadheading allowed"
SUBTITLE = "Minimum fleet with empty repositioning, typical Monday"


if __name__ == "__main__":
    print_block_length_stats(blocks_dict, HEADING)
    print()
    print(f"Wrote bar chart to {plot_block_lengths(blocks_dict, PATH, TITLE, SUBTITLE)}")
