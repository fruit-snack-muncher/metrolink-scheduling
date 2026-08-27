"""Block length distribution: statistics and bar chart.

Each block is one trainset's whole Monday, so its length is the number of
revenue trips that trainset turns. The shape of the distribution is what says
whether a fleet count is being bought honestly - work spread evenly across the
sets - or by a few very long blocks carrying the day while most trainsets turn
one or two trips.

Nothing here solves anything. Every function takes a `blocks_dict` of
`block number -> list of trip ids`, exactly as the model modules expose it, so
this module is shared by every fleet variant rather than tied to one. The
callers are the sibling `*_viz.py` scripts.
"""

from pathlib import Path
import statistics
import matplotlib
matplotlib.use("Agg")  # No GUI; we only ever write a file.
import matplotlib.pyplot as plt

# Charts land in figures/ at the repository root, located relative to this
# file rather than the working directory, so the scripts run from anywhere.
FIGURES = Path(__file__).resolve().parent.parent.parent / "figures"


def block_lengths(blocks_dict: dict) -> dict:
    """Trips per block, keyed by block number."""
    return {block_num: len(block) for block_num, block in blocks_dict.items()}


def block_length_stats(blocks_dict: dict) -> dict:
    """Summary statistics for the per-block trip counts.

    Outliers are the standard Tukey rule: a block is an outlier when its length
    falls outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]. Quartiles use the inclusive
    method so Q1/Q3 stay comparable to the ones numpy and R's type-7 report.
    """
    lengths_by_block = block_lengths(blocks_dict)
    lengths = sorted(lengths_by_block.values())
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
        "outliers": {block_num: length for block_num, length in lengths_by_block.items()
                     if length < lower_fence or length > upper_fence},
    }


def print_block_length_stats(blocks_dict: dict, heading: str = "Block lengths") -> None:
    """Prints the block length distribution and its summary statistics.

    `heading` names the fleet variant; the block and trip counts are appended
    to it.
    """
    lengths_by_block = block_lengths(blocks_dict)
    stats = block_length_stats(blocks_dict)

    print(f"{heading} ({stats['n_blocks']} blocks, {stats['n_trips']} trips)")
    print()
    for block_num, length in lengths_by_block.items():
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


def plot_block_lengths(blocks_dict: dict, path: Path,
                       title: str = "Trips per block",
                       subtitle: str = "Typical Monday",
                       groups: dict | None = None,
                       group_order: list | None = None,
                       group_label=str) -> Path:
    """Saves a bar chart of trip count by block number. Returns the path written.

    `subtitle` describes the fleet variant; the block and trip counts are
    appended to it.

    `groups` optionally partitions the blocks - block number -> group key, as the
    multi-depot fleet partitions by home depot. Bars are then laid out one group
    at a time, separated by a gap and coloured per group, so the distribution can
    be read within a group and across groups at once. `group_order` fixes the
    left-to-right order (default: sorted); `group_label` names a group in the
    legend and above its band. The statistics, fences and mean/median lines stay
    fleet-wide either way: the question is how each group sits in the whole
    distribution, not how it compares against itself.
    """
    lengths_by_block = block_lengths(blocks_dict)
    stats = block_length_stats(blocks_dict)

    SURFACE, INK, INK_SECONDARY, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
    GRID, BASELINE = "#e1e0d9", "#c3c2b7"
    TYPICAL, OUTLIER = "#2a78d6", "#d03b3b"  # categorical slot 1; status "critical"
    GROUP_COLORS = (TYPICAL, "#12897b", "#b8620e", "#7a5bd0")  # categorical slots 1-4
    GROUP_GAP = 2.0  # Blank x units between one group's last bar and the next group's first.

    # Bars are drawn at `positions`, which equal the block numbers unless a partition
    # opens a gap between groups. `order` is the left-to-right block sequence.
    block_nums = sorted(lengths_by_block)
    if groups is None:
        order = block_nums
        positions = {n: float(n) for n in block_nums}
        group_keys, group_spans, boundaries = [], {}, []
        colors = [OUTLIER if n in stats["outliers"] else TYPICAL for n in block_nums]
    else:
        group_keys = list(group_order) if group_order else sorted({groups[n] for n in block_nums})
        color_of = {key: GROUP_COLORS[i % len(GROUP_COLORS)] for i, key in enumerate(group_keys)}

        order, positions, group_spans, boundaries = [], {}, {}, []
        x, last_position = 1.0, None
        for key in group_keys:
            members = [n for n in block_nums if groups[n] == key]
            if last_position is not None:
                boundaries.append((last_position + x) / 2)
            start = x
            for n in members:
                order.append(n)
                positions[n] = x
                x += 1
            last_position = x - 1
            group_spans[key] = (start, last_position)
            x += GROUP_GAP
        colors = [OUTLIER if n in stats["outliers"] else color_of[groups[n]] for n in order]

    block_nums = order
    lengths = [lengths_by_block[n] for n in block_nums]
    bar_positions = [positions[n] for n in block_nums]

    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bars = ax.bar(bar_positions, lengths, color=colors, zorder=3)

    # Mean, median, and a +/-1 SD band, all drawn under the bars. The two lines
    # land within a few tenths of each other whenever the distribution is near
    # symmetric, which is too close for separate margin labels, so the legend
    # carries the values instead.
    mean, sd = stats["mean"], stats["stdev"]
    ax.axhspan(mean - sd, mean + sd, color=TYPICAL, alpha=0.10, zorder=1)
    ax.axhline(stats["median"], color=MUTED, linewidth=1, linestyle=(0, (4, 3)), zorder=2)
    ax.axhline(mean, color=INK_SECONDARY, linewidth=1, zorder=2)

    # Group bands: a hairline in the gap, and the group's name over its own bars.
    for boundary in boundaries:
        ax.axvline(boundary, color=GRID, linewidth=1, zorder=1)
    for key in group_keys:
        start, end = group_spans[key]
        ax.annotate(group_label(key), xy=((start + end) / 2, max(lengths) + 1.3),
                    ha="center", va="center", fontsize=8, color=INK_SECONDARY)

    # Only the extremes are directly labelled; the axis carries everything else.
    for bar, block_num, length in zip(bars, block_nums, lengths):
        if block_num in stats["outliers"]:
            ax.annotate(str(length), xy=(bar.get_x() + bar.get_width() / 2, length),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color=INK_SECONDARY)

    ax.set_title(title, fontsize=13, color=INK, loc="left", pad=18, weight="bold")
    ax.annotate(f"{subtitle} - "
                f"{stats['n_blocks']} blocks covering {stats['n_trips']} trips",
                xy=(0, 1), xycoords="axes fraction", xytext=(0, 10),
                textcoords="offset points", fontsize=9, color=INK_SECONDARY)
    ax.set_xlabel("Block number", fontsize=9, color=INK_SECONDARY, labelpad=8)
    ax.set_ylabel("Trips in block", fontsize=9, color=INK_SECONDARY, labelpad=8)

    ax.set_xticks(bar_positions)
    ax.set_xticklabels(block_nums, fontsize=7)
    # Stop the ticks at the tallest bar so no gridline runs behind the legend.
    ax.set_yticks(range(0, max(lengths) + 1, 2))
    ax.set_xlim(min(bar_positions) - 0.6, max(bar_positions) + 0.6)
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

    if groups is None:
        block_handles, block_labels = [plt.Rectangle((0, 0), 1, 1, color=TYPICAL)], ["Block"]
    else:
        block_handles = [plt.Rectangle((0, 0), 1, 1, color=color_of[key]) for key in group_keys]
        block_labels = [f"{group_label(key)} "
                        f"({sum(1 for n in block_nums if groups[n] == key)} blocks)"
                        for key in group_keys]

    handles = block_handles + [
        plt.Rectangle((0, 0), 1, 1, color=OUTLIER),
        plt.Line2D([], [], color=INK_SECONDARY, linewidth=1),
        plt.Line2D([], [], color=MUTED, linewidth=1, linestyle=(0, (4, 3))),
        plt.Rectangle((0, 0), 1, 1, color=TYPICAL, alpha=0.10)]
    legend = ax.legend(handles,
                       block_labels +
                       [f"Outlier (outside {stats['lower_fence']:.1f}-{stats['upper_fence']:.1f} trips)",
                        f"Mean {mean:.2f}",
                        f"Median {stats['median']:.1f}",
                        f"+/-1 SD ({sd:.2f})"],
                       frameon=False, fontsize=8, loc="upper left", handlelength=1.2,
                       handleheight=1.2, labelcolor=INK_SECONDARY)
    legend.set_zorder(4)

    fig.tight_layout()

    # Cap the rendered bar thickness at 24px and leave a 2px gap between
    # neighbours. Needs the drawn axes width, so it happens after tight_layout.
    fig.canvas.draw()
    left, right = ax.get_xlim()
    band_px = ax.get_window_extent().width / (right - left)  # Pixels per x unit, i.e. per bar slot.
    width = min(24.0, max(band_px - 2.0, 1.0)) / band_px
    for bar, position in zip(bars, bar_positions):
        bar.set_x(position - width / 2)
        bar.set_width(width)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path
