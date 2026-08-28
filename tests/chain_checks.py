"""Turning a solver's chosen arcs back into the trainset diagrams they encode.

Every solver in src/solvers hands back a FLAT list of arcs - `(tripA, tripB)`
pairs, in no particular order, with nothing saying which arcs belong to the same
trainset. That list is the LP's answer, but it is not the thing a reader wants to
check. The thing worth checking is the day each trainset actually works: a
sequence of trips, in order, that one set can physically run.

Recovering that sequence is only possible because of the path-cover rows in
min_path_cover and the flow-requirement rows in multi_depot: at most one arc
leaves each trip and at most one enters it. That makes the arcs a set of
vertex-disjoint paths, so following successors from a trip with no predecessor
walks exactly one trainset's day and every trip lies on exactly one such walk.

`link_maps` exposes that structure directly, so a test can assert the property
rather than assume it; `chains` does the walk. Neither asserts anything itself -
a helper that swallowed a violation would hide the failure it exists to surface -
so both raise ValueError on arcs that are not a path cover, and the test files
check the property explicitly before relying on it.

Note there is no cycle guard, and none is needed. `chains` starts only from trips
with no predecessor, so a cycle is unreachable from any start: its trips simply go
uncovered, and the partition check in the caller fails with the trips named.
"""


def link_maps(arcs) -> tuple[dict[int, int], dict[int, int]]:
    """`(successor, predecessor)`: trip -> the trip chained after / before it.

    Raises ValueError if any trip is left by two arcs or entered by two, which is
    exactly the path-cover property failing. Trips at the end (or start) of their
    chain are absent from `successor` (or `predecessor`) rather than mapped to None,
    so `in` is the test for a chain end.
    """
    successor: dict[int, int] = {}
    predecessor: dict[int, int] = {}
    for tripA, tripB in arcs:
        if tripA in successor:
            raise ValueError(f"trip {tripA} is chained into both {successor[tripA]} and {tripB}")
        if tripB in predecessor:
            raise ValueError(f"trip {tripB} is chained from both {predecessor[tripB]} and {tripA}")
        successor[tripA] = tripB
        predecessor[tripB] = tripA
    return successor, predecessor


def chains(trip_ids, arcs) -> list[list[int]]:
    """One list of trip_ids per trainset, each in the order that set runs them.

    A trip covered by no arc at all is its own one-trip chain - a trainset that
    works once and is done - so `len(chains(...))` is the fleet size, and the
    chains partition `trip_ids` whenever the arcs are a genuine path cover over
    them. Ordered by chain start, so the result is stable to compare.
    """
    successor, predecessor = link_maps(arcs)
    unknown = (set(successor) | set(predecessor)) - set(trip_ids)
    if unknown:
        raise ValueError(f"arcs name trips outside the schedule: {sorted(unknown)}")

    built = []
    for start in sorted(t for t in trip_ids if t not in predecessor):
        chain, trip = [start], start
        while trip in successor:
            trip = successor[trip]
            chain.append(trip)
        built.append(chain)
    return built
