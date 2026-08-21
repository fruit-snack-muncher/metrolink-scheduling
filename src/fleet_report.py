"""Operability statistics for a solved fleet: spans, balance, utilisation, deadheads.

`viz/block_lengths.py` answers how much work each trainset does. This module
answers where that work happens and what it costs to position for it - the
questions that decide whether a fleet count is operable rather than merely
optimal.

Every function takes a `blocks_dict` of `block number -> list of trip ids`, 
exactly as the model modules expose it, so one module serves every fleet variant. 
Trip ids arrive as strings from the models and index `typical_monday_trip_schedule` 
as ints; the conversion is done here rather than pushed onto callers.

Four questions, one function each:

  block_spans        Where does each block start and end, and how long is it?
  endpoint_balance   Do the blocks leave the fleet where tomorrow needs it?
  utilisation        How much of a set's day is revenue service?
  deadhead_census    Which turns are empty moves, and how long do they run?

The base model cannot deadhead by construction, so `deadhead_census` returns no
moves for it. That is a useful self-check rather than a special case.
"""

from preformulation import typical_monday_deadhead_times
from typical_monday_trips import typical_monday_trip_schedule, stops

def hhmmss(seconds: int) -> str:
    """Seconds past midnight as HH:MM:SS.

    Hours are not capped at 24: GTFS writes a trip running past midnight as
    e.g. 25:10:00, and the seconds count preserves that.
    """
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

def stop_name(stop_id: int) -> str:
    """Station name for a GTFS stop_id."""
    return stops.loc[stops.stop_id == stop_id, "stop_name"].values[0]

def block_spans(blocks_dict: dict) -> dict:
    """Origin, terminus, start, end and span for each block.

    The span is first departure to last arrival - the whole time the trainset is
    committed, revenue service and idling alike. Times are seconds past
    midnight; stations are returned both as stop_ids and as names, since the
    balance calculation wants to group on one and print the other.
    """
    spans = {}
    for block_num, block in blocks_dict.items():
        first_trip, last_trip = int(block[0]), int(block[-1])
        origin, _, start, _ = typical_monday_trip_schedule[first_trip]
        _, terminus, _, end = typical_monday_trip_schedule[last_trip]
        spans[block_num] = {
            "origin_id": origin,
            "terminus_id": terminus,
            "origin": stop_name(origin),
            "terminus": stop_name(terminus),
            "start": start,
            "end": end,
            "span": end - start,
        }
    return spans

def endpoint_balance(blocks_dict: dict) -> dict:
    """Blocks originating vs terminating at each station.

    A schedule that repeats daily needs the multiset of block origins to equal
    the multiset of termini: every set must finish where some set has to start
    tomorrow. Where they differ, the surplus has to be repositioned overnight by
    a move no single-day model prices.

    Returns station name -> {"origins", "termini", "deficit"}, where deficit is
    origins - termini. Negative means sets pile up there; positive means the
    station needs sets it did not receive.
    """
    spans = block_spans(blocks_dict)
    balance = {}
    for info in spans.values():
        for station, key in ((info["origin"], "origins"), (info["terminus"], "termini")):
            entry = balance.setdefault(station, {"origins": 0, "termini": 0})
            entry[key] += 1
    for entry in balance.values():
        entry["deficit"] = entry["origins"] - entry["termini"]
    return balance

def utilisation(blocks_dict: dict) -> dict:
    """Revenue seconds against total block seconds.

    Revenue time is fixed by the schedule - it is the same 132 trips however
    they are chained - so this ratio moves only through the denominator. A
    smaller fleet spreads the same revenue work over fewer, longer blocks.
    """
    revenue = sum(
        typical_monday_trip_schedule[int(trip)][3] - typical_monday_trip_schedule[int(trip)][2]
        for block in blocks_dict.values()
        for trip in block
    )
    block_time = sum(info["span"] for info in block_spans(blocks_dict).values())
    return {
        "revenue_seconds": revenue,
        "block_seconds": block_time,
        "share": revenue / block_time,
    }

def deadhead_census(blocks_dict: dict) -> dict:
    """Every turn inside a block, split into empty moves and same-station turns.

    A turn is a consecutive pair of trips in one block. When the first ends
    where the second begins the set simply changes ends; otherwise it must run
    empty, and the move costs the shortest-path time computed in
    `preformulation`. `gap` is the whole window between arrival and departure,
    so `gap - deadhead` is the slack left for the two turnarounds the chaining
    rule requires.

    Moves are returned longest first, which is the order worth eyeballing.
    """
    moves, same_station = [], 0
    for block_num, block in blocks_dict.items():
        for first, second in zip(block, block[1:]):
            _, arrival, _, arrival_time = typical_monday_trip_schedule[int(first)]
            departure, _, departure_time, _ = typical_monday_trip_schedule[int(second)]
            if arrival == departure:
                same_station += 1
                continue
            moves.append({
                "block": block_num,
                "from": stop_name(arrival),
                "to": stop_name(departure),
                "deadhead": typical_monday_deadhead_times[frozenset([arrival, departure])],
                "gap": departure_time - arrival_time,
            })

    moves.sort(key=lambda move: -move["deadhead"])
    total = sum(move["deadhead"] for move in moves)
    return {
        "moves": moves,
        "n_deadheads": len(moves),
        "n_same_station": same_station,
        "n_turns": len(moves) + same_station,
        "total_seconds": total,
        "mean_seconds": total / len(moves) if moves else 0,
    }

def print_fleet_report(blocks_dict: dict, heading: str = "Fleet report") -> None:
    """Prints all four analyses for one solved fleet."""
    spans = block_spans(blocks_dict)
    balance = endpoint_balance(blocks_dict)
    use = utilisation(blocks_dict)
    census = deadhead_census(blocks_dict)

    print(f"{heading} ({len(blocks_dict)} blocks)")

    print("\n  Blocks")
    for block_num in sorted(spans):
        info = spans[block_num]
        print(f"    {block_num:>2}  {info['origin']:<34} -> {info['terminus']:<34}"
              f"  {hhmmss(info['start'])} -> {hhmmss(info['end'])}"
              f"  span {hhmmss(info['span'])}")

    all_spans = sorted(info["span"] for info in spans.values())
    median = all_spans[len(all_spans) // 2] if len(all_spans) % 2 else \
        (all_spans[len(all_spans) // 2 - 1] + all_spans[len(all_spans) // 2]) // 2
    print(f"\n    span min / median / max   {hhmmss(all_spans[0])} / "
          f"{hhmmss(median)} / {hhmmss(all_spans[-1])}")

    print("\n  Endpoint balance")
    for station in sorted(balance):
        entry = balance[station]
        flag = "" if entry["deficit"] == 0 else f"   <- {entry['deficit']:+d}"
        print(f"    {station:<34}  {entry['origins']:>2} out  {entry['termini']:>2} in{flag}")
    unbalanced = {s: e["deficit"] for s, e in balance.items() if e["deficit"]}
    if unbalanced:
        stranded = sum(d for d in unbalanced.values() if d < 0)
        print(f"    {-stranded} block(s) finish out of position across "
              f"{len(unbalanced)} station(s)")
    else:
        print("    balanced: every station sends out as many blocks as it receives")

    print("\n  Utilisation")
    print(f"    revenue {use['revenue_seconds'] / 3600:.0f} h of "
          f"{use['block_seconds'] / 3600:.0f} block-hours = {use['share']:.0%}")

    print("\n  Turns")
    print(f"    {census['n_turns']} turns: {census['n_deadheads']} deadhead(s), "
          f"{census['n_same_station']} same-station")
    if census["moves"]:
        print(f"    {census['total_seconds'] / 3600:.2f} h empty running, "
              f"mean {census['mean_seconds'] / 60:.0f} min")
        for move in census["moves"]:
            print(f"      blk {move['block']:>2}  {move['from']:<34} -> {move['to']:<34}"
                  f"  {move['deadhead'] / 3600:.2f} h empty"
                  f"  of {move['gap'] / 3600:.2f} h gap")

if __name__ == "__main__":
    # Imported here, not at module scope: each one builds and solves an LP, and
    # the functions above are useful without paying for either.
    import zero_depot
    import zero_depot_deadheading

    print_fleet_report(zero_depot.blocks_dict, "No deadheading")
    print()
    print_fleet_report(zero_depot_deadheading.blocks_dict, "Deadheading, penalised")
