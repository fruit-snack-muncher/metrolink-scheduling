"""Block length distribution for the zero-depot minimum fleet.

A lopsided distribution - a few very long blocks carrying the day while most
trainsets turn one or two trips - would be a sign the zero-depot relaxation is
buying its 35 by chaining trips a real operator could not chain back-to-back.

The blocks themselves come from zero_depot; importing it runs the LP solve
once, and nothing here re-derives them. The statistics and the chart live in
block_lengths, shared with the deadheading variant.
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
from zero_depot import blocks_dict

PATH = FIGURES / "block_lengths.png"
HEADING = "Block lengths"
TITLE = "Trips per block"
SUBTITLE = "Zero-depot minimum fleet, typical Monday"


if __name__ == "__main__":
    print_block_length_stats(blocks_dict, HEADING)
    print()
    print(f"Wrote bar chart to {plot_block_lengths(blocks_dict, PATH, TITLE, SUBTITLE)}")
