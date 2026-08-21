"""Block length distribution for the minimum fleet with deadheading allowed.

The counterpart to zero_depot_viz. A set may now reposition empty between two
trips, so a block no longer has to stay where it last stopped. The question the
distribution answers is whether the four trainsets deadheading saves come from
spreading work more evenly or from a handful of blocks absorbing everything.

The blocks themselves come from zero_depot_deadheading; importing it runs the
LP solve once, and nothing here re-derives them. The statistics and the chart
live in block_lengths, shared with the zero-depot variant.
"""

import sys
from pathlib import Path

# src/ holds the model modules, src/viz/ the plotting ones. Both go on the path
# so this runs as a plain script from any working directory, the same fallback
# src/conftest.py provides for the test suite.
for _dir in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from block_lengths import FIGURES, plot_block_lengths, print_block_length_stats
from zero_depot_deadheading import blocks_dict

PATH = FIGURES / "block_lengths_deadheading.png"
HEADING = "Block lengths, deadheading allowed"
TITLE = "Trips per block, deadheading allowed"
SUBTITLE = "Minimum fleet with empty repositioning, typical Monday"


if __name__ == "__main__":
    print_block_length_stats(blocks_dict, HEADING)
    print()
    print(f"Wrote bar chart to {plot_block_lengths(blocks_dict, PATH, TITLE, SUBTITLE)}")
