"""Shared analysis for a solved fleet: block reconstruction, spans, endpoint
balance, utilisation, deadhead census.

Every function takes a `blocks_dict` of block number -> list of trip ids, so one
module serves every variant. Trip ids are strings here and ints in
`typical_monday_trip_schedule`; the conversion is done here, not by callers.
"""

from src.data_processing.preformulation import typical_monday_deadhead_times
from src.data_processing.typical_monday_trips import typical_monday_trip_schedule, stops


def hhmmss(seconds: int) -> str:
    """Seconds past midnight as HH:MM:SS. Hours are not capped at 24: GTFS
    writes a trip running past midnight as e.g. 25:10:00."""
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"


def stop_name(stop_id: int) -> str:
    """Station name for a GTFS stop_id."""
    return stops.loc[stops.stop_id == stop_id, "stop_name"].values[0]


def blocks_from_solution(trip_ids, arcs) -> dict:
    """Decomposes the solved DAG into blocks, one per trainset.

    The chosen arcs form vertex-disjoint directed paths, so each trip with no
    incoming arc starts a block that is walked forward to its end.
    """
    arc_departures = {str(a): str(b) for a, b in arcs}
    arc_arrivals = set(arc_departures.values())  # fast lookup

    blocks = []
    for t in map(str, trip_ids):
        if t not in arc_arrivals:
            block, current = [t], t
            while current in arc_departures:
                current = arc_departures[current]
                block.append(current)
            blocks.append(block)

    # No trainset performs the same trip twice in a row, and the paths partition
    # the trips: every trip is served exactly once, by exactly one block.
    for block in blocks:
        assert all(first != second for first, second in zip(block, block[1:]))
    assert sum(len(block) for block in blocks) == len(trip_ids)

    return {i + 1: block for i, block in enumerate(blocks)}


def block_spans(blocks_dict: dict) -> dict:
    """Origin, terminus, start, end and span for each block.

    The span is first departure to last arrival - the whole time the trainset is
    committed, revenue service and idling alike. Stations come back as both
    stop_ids and names, since the balance groups on one and prints the other.
    """
    spans = {}
    for block_num, block in blocks_dict.items():
        origin, _, start, _ = typical_monday_trip_schedule[int(block[0])]
        _, terminus, _, end = typical_monday_trip_schedule[int(block[-1])]
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

    A schedule that repeats daily needs every set to finish where some set has
    to start tomorrow. Returns station -> {"origins", "termini", "deficit"},
    deficit being origins - termini: negative means sets pile up there, positive
    means the station needs sets it did not receive, and the surplus has to be
    repositioned overnight by a move no single-day model prices.
    """
    balance = {}
    for info in block_spans(blocks_dict).values():
        for station, key in ((info["origin"], "origins"), (info["terminus"], "termini")):
            entry = balance.setdefault(station, {"origins": 0, "termini": 0})
            entry[key] += 1
    for entry in balance.values():
        entry["deficit"] = entry["origins"] - entry["termini"]
    return balance


def utilisation(blocks_dict: dict) -> dict:
    """Revenue seconds against total block seconds.

    Revenue time is fixed by the schedule - the same 132 trips however they are
    chained - so this ratio moves only through the denominator.
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

    When a trip ends where the next begins the set simply changes ends;
    otherwise it runs empty, costing the shortest-path time from
    `preformulation`. `gap` is the whole window between arrival and departure,
    so gap - deadhead is the slack left for the two turnarounds. Moves are
    returned longest first.
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


def format_blocks(blocks_dict: dict) -> str:
    """One line per block: the chain of trips that trainset runs."""
    return "\n".join(f"Block {block_num:02} ({len(block)} total trips): {' -> '.join(block)}"
                     for block_num, block in sorted(blocks_dict.items()))


def format_fleet_report(blocks_dict: dict, heading: str = "Fleet report") -> str:
    """All four analyses for one solved fleet, as text.

    Returns rather than prints, so the report scripts can assemble a whole document and
    write it to its .md themselves - see analysis/markdown_report.py.
    """
    spans = block_spans(blocks_dict)
    balance = endpoint_balance(blocks_dict)
    use = utilisation(blocks_dict)
    census = deadhead_census(blocks_dict)

    lines = [f"{heading} ({len(blocks_dict)} blocks)"]

    lines.append("\n  Blocks")
    for block_num in sorted(spans):
        info = spans[block_num]
        lines.append(f"    {block_num:>2}  {info['origin']:<34} -> {info['terminus']:<34}"
                     f"  {hhmmss(info['start'])} -> {hhmmss(info['end'])}"
                     f"  span {hhmmss(info['span'])}")

    all_spans = sorted(info["span"] for info in spans.values())
    median = all_spans[len(all_spans) // 2] if len(all_spans) % 2 else \
        (all_spans[len(all_spans) // 2 - 1] + all_spans[len(all_spans) // 2]) // 2
    lines.append(f"\n    span min / median / max   {hhmmss(all_spans[0])} / "
                 f"{hhmmss(median)} / {hhmmss(all_spans[-1])}")

    lines.append("\n  Endpoint balance")
    for station in sorted(balance):
        entry = balance[station]
        flag = "" if entry["deficit"] == 0 else f"   <- {entry['deficit']:+d}"
        lines.append(f"    {station:<34}  {entry['origins']:>2} out  {entry['termini']:>2} in{flag}")
    unbalanced = {s: e["deficit"] for s, e in balance.items() if e["deficit"]}
    if unbalanced:
        stranded = sum(d for d in unbalanced.values() if d < 0)
        lines.append(f"    {-stranded} block(s) finish out of position across "
                     f"{len(unbalanced)} station(s)")
    else:
        lines.append("    balanced: every station sends out as many blocks as it receives")

    lines.append("\n  Utilisation")
    lines.append(f"    revenue {use['revenue_seconds'] / 3600:.0f} h of "
                 f"{use['block_seconds'] / 3600:.0f} block-hours = {use['share']:.0%}")

    lines.append("\n  Turns")
    lines.append(f"    {census['n_turns']} turns: {census['n_deadheads']} deadhead(s), "
                 f"{census['n_same_station']} same-station")
    if census["moves"]:
        lines.append(f"    {hhmmss(census['total_seconds'])} empty running, "
                     f"mean {census['mean_seconds'] / 60:.0f} min")
        for move in census["moves"]:
            lines.append(f"      blk {move['block']:>2}  {move['from']:<34} -> {move['to']:<34}"
                         f"  {move['deadhead'] / 3600:.2f} h empty"
                         f"  of {move['gap'] / 3600:.2f} h gap")

    return "\n".join(lines)
