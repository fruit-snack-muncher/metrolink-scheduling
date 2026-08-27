"""Block length distribution for the zero-depot minimum fleet.

A lopsided distribution - a few very long blocks carrying the day while most
trainsets turn one or two trips - would be a sign the zero-depot relaxation is
buying its 35 by chaining trips a real operator could not chain back-to-back.

The blocks themselves come from zero_depot_report; importing it runs the LP
solve once, and nothing here re-derives them. The statistics and the chart live
in block_lengths, shared with the deadheading variant.
"""

from src.analysis.zero_depot_report import blocks_dict
from src.viz.block_lengths import FIGURES, plot_block_lengths, print_block_length_stats

PATH = FIGURES / "block_lengths.png"
HEADING = "Block lengths"
TITLE = "Trips per block"
SUBTITLE = "Zero-depot minimum fleet, typical Monday"


if __name__ == "__main__":
    print_block_length_stats(blocks_dict, HEADING)
    print()
    print(f"Wrote bar chart to {plot_block_lengths(blocks_dict, PATH, TITLE, SUBTITLE)}")
