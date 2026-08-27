"""Fleet report for the multi-depot fleet (solvers/multi_depot.py).

The zero-depot reports treat the fleet as one pool. Here every trainset belongs to
an overnight depot and has to be back there by the end of the day, so the blocks
**partition** by depot: each block is flown by one set out of one depot, and the
per-depot slices below cover every block exactly once. The fleet report is printed
once per depot and then once fleet-wide, so a depot's blocks can be read as the
duty roster of that facility rather than as a slice of an anonymous fleet.

What this report adds beyond the shared analysis is the pair of empty moves the
zero-depot models could not see: depot -> first trip in the morning, and last trip
-> depot at night. `fleet_report.deadhead_census` counts only the turns *inside* a
block, so those legs are censused separately here.
"""

from src.analysis.fleet_report import (block_spans, blocks_from_solution, hhmmss,
                                       print_blocks, print_fleet_report, stop_name)
from src.data_processing.preformulation import (OVERNIGHT_CAPACITIES, OVERNIGHT_DEPOTS,
                                                typical_monday_deadhead_times)
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.multi_depot import (arcs, depot_fleet_sizes, fleet_size, home_depots,
                                     status, terminal_depots)

blocks_dict = blocks_from_solution(typical_monday_trip_ids, arcs)

# A block's home depot is the depot its first trip was drawn from. The solver guarantees one
# such depot per chain; the asserts below are what makes that guarantee visible here.
depot_of_block = {block_num: home_depots[int(block[0])]
                  for block_num, block in blocks_dict.items()}
blocks_by_depot = {depot: {block_num: block for block_num, block in blocks_dict.items()
                           if depot_of_block[block_num] == depot}
                   for depot in OVERNIGHT_DEPOTS}

assert status == "Optimal"
assert fleet_size == len(blocks_dict) == sum(len(blocks) for blocks in blocks_by_depot.values())
for depot, blocks in blocks_by_depot.items():
    assert len(blocks) == depot_fleet_sizes[depot]
# DEPOT FAITHFULNESS as it actually lands: every set returns to the depot it came from.
for block_num, block in blocks_dict.items():
    assert terminal_depots[int(block[-1])] == depot_of_block[block_num]


def depot_leg_seconds(stop_id: int, depot: int) -> int:
    """Empty running between a depot and a block endpoint, in seconds.

    Zero when the block already starts or ends at its own depot - the set is
    where it needs to be and runs no empty miles.
    """
    if stop_id == depot:
        return 0
    return typical_monday_deadhead_times[frozenset([stop_id, depot])]


def depot_legs(blocks_dict: dict, depot_of_block: dict) -> dict:
    """The morning and evening empty moves for each block, and their totals.

    Each block contributes two legs, either of which may be zero-length. `legs` is
    returned worst first, by the block's combined empty time, so the blocks that
    cost the most to position read off the top.
    """
    spans = block_spans(blocks_dict)
    legs = []
    for block_num, info in spans.items():
        depot = depot_of_block[block_num]
        out_seconds = depot_leg_seconds(info["origin_id"], depot)
        back_seconds = depot_leg_seconds(info["terminus_id"], depot)
        legs.append({
            "block": block_num,
            "depot": depot,
            "origin": info["origin"],
            "terminus": info["terminus"],
            "out_seconds": out_seconds,
            "back_seconds": back_seconds,
            "total_seconds": out_seconds + back_seconds,
        })

    legs.sort(key=lambda leg: -leg["total_seconds"])
    return {
        "legs": legs,
        "n_empty_legs": sum((leg["out_seconds"] > 0) + (leg["back_seconds"] > 0) for leg in legs),
        "n_at_depot_legs": sum((leg["out_seconds"] == 0) + (leg["back_seconds"] == 0) for leg in legs),
        "total_seconds": sum(leg["total_seconds"] for leg in legs),
    }


def print_depot_legs(census: dict, heading: str = "Depot positioning") -> None:
    """Prints the depot legs, one line per block that runs empty at either end."""
    print(f"{heading} ({census['n_empty_legs']} empty legs, "
          f"{census['n_at_depot_legs']} already at depot)")
    print(f"    {hhmmss(census['total_seconds'])} empty running to and from depots")
    for leg in census["legs"]:
        if leg["total_seconds"] == 0:
            continue  # Starts and ends at its own depot; nothing to position.
        print(f"      blk {leg['block']:>2}  depot {leg['depot']:<4} "
              f"{leg['out_seconds'] / 3600:.2f} h out to {leg['origin']:<34}"
              f"  {leg['back_seconds'] / 3600:.2f} h back from {leg['terminus']}")


legs_census = depot_legs(blocks_dict, depot_of_block)

if __name__ == "__main__":
    for depot, capacity in zip(OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES):
        blocks = blocks_by_depot[depot]
        heading = f"Depot {depot}, {stop_name(depot)} - {len(blocks)} of {capacity} trainsets"
        print(f"\n{'=' * len(heading)}\n{heading}\n{'=' * len(heading)}\n")
        print_blocks(blocks)
        print()
        print_fleet_report(blocks, heading)

    print(f"\nMinimum fleet size: {fleet_size} trainsets over {len(blocks_dict)} blocks, "
          f"{' + '.join(f'{n} at {d}' for d, n in depot_fleet_sizes.items())}.\n")
    print_fleet_report(blocks_dict, "Multi-depot, fleet-wide")
    print()
    print_depot_legs(legs_census)
