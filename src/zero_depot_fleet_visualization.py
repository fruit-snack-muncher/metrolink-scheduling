"""Block length distribution for the zero-depot minimum fleet.

Each block is one trainset's whole Monday, so its length is the number of
revenue trips that trainset turns. A lopsided distribution - a few very long
blocks carrying the day while most trainsets turn one or two trips - is a sign
the zero-depot relaxation is buying its 38 by chaining trips a real operator
could not chain back-to-back.

The blocks themselves come from zero_depot_fleet; importing it runs the LP solve
once, and nothing here re-derives them.
"""

from zero_depot_fleet import blocks_dict
from pathlib import Path
import statistics
import matplotlib
matplotlib.use("Agg")  # No GUI; we only ever write a file.
import matplotlib.pyplot as plt

# Trips per block, keyed by block number.
block_lengths = {block_num: len(block) for block_num, block in blocks_dict.items()}


def block_length_stats() -> dict:
    """Summary statistics for the per-block trip counts.

    Outliers are the standard Tukey rule: a block is an outlier when its length
    falls outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]. Quartiles use the inclusive
    method so Q1/Q3 stay comparable to the ones numpy and R's type-7 report.
    """
    lengths = sorted(block_lengths.values())
    q1, median, q3 = statistics.quantiles(lengths, n=4, method="inclusive")
    iqr = q3 - q1
    lower_fence, upper_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr

    return {
        "n_blocks": len(lengths),
        "n_trips": sum(lengths),
        "min": lengths[0],
        "max": lengths[-1],
        "mean": statistics.fmean(lengths),
        "median": median,
        "mode": statistics.multimode(lengths),
        "stdev": statistics.stdev(lengths),
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "lower_fence": lower_fence,
        "upper_fence": upper_fence,
        # Block number -> length, for every block outside the fences.
        "outliers": {block_num: length for block_num, length in block_lengths.items()
                     if length < lower_fence or length > upper_fence},
    }


def print_block_length_stats() -> None:
    """Prints the block length distribution and its summary statistics."""
    stats = block_length_stats()

    print(f"Block lengths ({stats['n_blocks']} blocks, {stats['n_trips']} trips)")
    print()
    for block_num, length in block_lengths.items():
        flag = " <- outlier" if block_num in stats["outliers"] else ""
        print(f"  Block {block_num:>2}  {length:>2} trips{flag}")

    print()
    print(f"  min / max      {stats['min']} / {stats['max']}")
    print(f"  mean           {stats['mean']:.2f}")
    print(f"  median         {stats['median']:.1f}")
    print(f"  mode           {', '.join(str(m) for m in stats['mode'])}")
    print(f"  stdev          {stats['stdev']:.2f}")
    print(f"  Q1 / Q3 (IQR)  {stats['q1']:.1f} / {stats['q3']:.1f} ({stats['iqr']:.1f})")
    print(f"  Tukey fences   [{stats['lower_fence']:.2f}, {stats['upper_fence']:.2f}]")
    if stats["outliers"]:
        listed = ", ".join(f"block {n} ({length} trips)"
                           for n, length in sorted(stats["outliers"].items(),
                                                   key=lambda kv: -kv[1]))
        print(f"  outliers       {listed}")
    else:
        print(f"  outliers       none")


def plot_block_lengths(path: Path = Path(__file__).parent.parent / "figures" / "block_lengths.png") -> Path:
    """Saves a bar chart of trip count by block number. Returns the path written."""
    stats = block_length_stats()

    SURFACE, INK, INK_SECONDARY, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
    GRID, BASELINE = "#e1e0d9", "#c3c2b7"
    TYPICAL, OUTLIER = "#2a78d6", "#d03b3b"  # categorical slot 1; status "critical"

    block_nums = list(block_lengths.keys())
    lengths = [block_lengths[n] for n in block_nums]
    colors = [OUTLIER if n in stats["outliers"] else TYPICAL for n in block_nums]

    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bars = ax.bar(block_nums, lengths, color=colors, zorder=3)

    # Median reference line, drawn under the bars and labelled in the margin.
    ax.axhline(stats["median"], color=MUTED, linewidth=1, linestyle=(0, (4, 3)), zorder=2)
    ax.annotate(f"median {stats['median']:.1f}",
                xy=(block_nums[-1] + 0.6, stats["median"]), xycoords="data",
                va="center", ha="left", fontsize=8, color=INK_SECONDARY,
                annotation_clip=False)

    # Only the extremes are directly labelled; the axis carries everything else.
    for bar, block_num, length in zip(bars, block_nums, lengths):
        if block_num in stats["outliers"]:
            ax.annotate(str(length), xy=(bar.get_x() + bar.get_width() / 2, length),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color=INK_SECONDARY)

    ax.set_title("Trips per block", fontsize=13, color=INK, loc="left", pad=18, weight="bold")
    ax.annotate("Zero-depot minimum fleet, typical Monday - "
                f"{stats['n_blocks']} blocks covering {stats['n_trips']} trips",
                xy=(0, 1), xycoords="axes fraction", xytext=(0, 10),
                textcoords="offset points", fontsize=9, color=INK_SECONDARY)
    ax.set_xlabel("Block number", fontsize=9, color=INK_SECONDARY, labelpad=8)
    ax.set_ylabel("Trips in block", fontsize=9, color=INK_SECONDARY, labelpad=8)

    ax.set_xticks(block_nums)
    ax.set_xticklabels(block_nums, fontsize=7)
    # Stop the ticks at the tallest bar so no gridline runs behind the legend.
    ax.set_yticks(range(0, max(lengths) + 1, 2))
    ax.set_xlim(0.4, len(block_nums) + 0.6)
    ax.set_ylim(0, max(lengths) + 2)  # Headroom for the outlier value labels.
    ax.tick_params(colors=MUTED, labelsize=8, length=0)

    # Recessive chrome: hairline horizontal grid, no box, baseline one step off surface.
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=1, linestyle="-")
    ax.xaxis.grid(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.spines["bottom"].set_linewidth(1)

    handles = [plt.Rectangle((0, 0), 1, 1, color=TYPICAL),
               plt.Rectangle((0, 0), 1, 1, color=OUTLIER)]
    legend = ax.legend(handles,
                       ["Block",
                        f"Outlier (outside {stats['lower_fence']:.1f}-{stats['upper_fence']:.1f} trips)"],
                       frameon=False, fontsize=8, loc="upper left", handlelength=1.2,
                       handleheight=1.2, labelcolor=INK_SECONDARY)
    legend.set_zorder(4)

    fig.tight_layout()

    # Cap the rendered bar thickness at 24px and leave a 2px gap between
    # neighbours. Needs the drawn axes width, so it happens after tight_layout.
    fig.canvas.draw()
    band_px = ax.get_window_extent().width / len(block_nums)
    width = min(24.0, max(band_px - 2.0, 1.0)) / band_px
    for bar, block_num in zip(bars, block_nums):
        bar.set_x(block_num - width / 2)
        bar.set_width(width)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


if __name__ == "__main__":
    print_block_length_stats()
    print()
    print(f"Wrote bar chart to {plot_block_lengths()}")
