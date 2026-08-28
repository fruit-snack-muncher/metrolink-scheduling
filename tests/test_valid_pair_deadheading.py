"""
Tests for preformulation.valid_pair_deadheading, and for the chains built on it.

valid_pair_deadheading(A, B, turnaround) asks the same question valid_pair does -
can one trainset run trip B after trip A - but lets the set REPOSITION EMPTY in
between. That splits the rule in two:

  * A ends where B begins. Nothing has changed; the set turns in place, and the
    predicate simply delegates to valid_pair.
  * A ends somewhere else. The set must run empty from A's arrival stop to B's
    departure stop, and the day has to hold all three of the turnaround at the
    near end, the empty run, and the turnaround at the far end:

        a_arr + turnaround + deadhead(a_to, b_from) + turnaround  <=  b_dep

The SECOND turnaround is the half that is easy to lose. A set that has just
arrived is not ready to move, and one that has just finished repositioning is not
ready to depart; dropping either would manufacture chainings that cannot be
operated, and every one of them removes a trainset from the reported fleet.

`deadhead` is the shortest path on an undirected graph of the stops served on a
typical Monday, edges weighted by mean consecutive-stop revenue running time. It
is symmetric by construction (the key is a frozenset), and it is float('inf') for
a stop no empty run can reach, which the `<=` then rejects on its own.

The suite runs in four layers:

  * SYNTHETIC   - a hand-built schedule and a hand-built distance table, pinning
                  the exact boundary and isolating each of the three terms.
  * PROPERTIES  - exhaustive sweeps over all 132^2 real pairs, asserting the
                  invariants the fleet model depends on, plus the relationship
                  the whole variant rests on: deadheading only ADDS arcs.
  * REAL PAIRS  - named cases from the GTFS data, as readable anchors.
  * CHAINS      - the diagrams zero_depot_deadheading actually returns, checked
                  against the predicate that was supposed to generate them.
"""

from itertools import product

import pytest

from src.data_processing import preformulation
from src.data_processing.preformulation import (
    TRAINSET_DAYS_PER_DEADHEAD_HOUR,
    TURNAROUND,
    valid_arcs,
    valid_arcs_deadheading,
    valid_pair,
    valid_pair_deadheading,
    weights_and_arcs,
)
from tests.chain_checks import chains, link_maps

# Real Metrolink stop_ids, used here purely as distinguishable labels.
LAUS = 107  # L.A. Union Station
LANCASTER = 162
SAN_BERNARDINO = 185
ISLAND = 999  # not a real stop: stands in for one no empty run can reach


# ==========================================================================
# Synthetic schedule and distances: the boundary, term by term
# ==========================================================================

# The hand-built distance table. Deliberately ASYMMETRIC in size between the two
# reachable pairs -- 5_000s to Lancaster against 3_000s to San Bernardino -- so a
# rule that used any single constant instead of the pair's own distance would show
# up. ISLAND is unreachable from everywhere, which is the inf branch.
SYNTHETIC_DEADHEAD_TIMES = {
    frozenset([LAUS, LANCASTER]): 5_000,
    frozenset([LAUS, SAN_BERNARDINO]): 3_000,
    frozenset([LANCASTER, SAN_BERNARDINO]): 8_000,
    frozenset([LAUS, ISLAND]): float("inf"),
    frozenset([LANCASTER, ISLAND]): float("inf"),
    frozenset([SAN_BERNARDINO, ISLAND]): float("inf"),
}

# Trips are the 4-tuples the predicate expects:
#     (departure stop_id, arrival stop_id, departure time, arrival time)
# with times in seconds past midnight.
#
# LEAD is the anchor again: it ends at LAUS at t=10_000. Every follower is placed
# relative to that arrival, and the two thresholds that matter are
#
#     same station          10_000 + 1_200                     = 11_200
#     empty run to Lancaster 10_000 + 1_200 + 5_000 + 1_200     = 17_400
SYNTHETIC_SCHEDULE = {
    "LEAD": (LANCASTER, LAUS, 0, 10_000),

    # --- the same-station branch, which must behave exactly like valid_pair ---
    "SAME_STATION_EXACT": (LAUS, LANCASTER, 11_200, 20_000),
    "SAME_STATION_SHORT": (LAUS, LANCASTER, 11_199, 20_000),

    # --- the deadhead branch, around 17_400 ---
    "DEADHEAD_EXACT": (LANCASTER, SAN_BERNARDINO, 17_400, 25_000),
    "DEADHEAD_ONE_SECOND_SHORT": (LANCASTER, SAN_BERNARDINO, 17_399, 25_000),

    # Arrival + one turnaround + the empty run, and nothing after it. Enough for a
    # set to reach Lancaster; not enough for it to be ready to work when it gets
    # there. This is the trip that a missing SECOND turnaround would accept.
    "SINGLE_TURNAROUND": (LANCASTER, SAN_BERNARDINO, 16_200, 25_000),

    # Arrival + the empty run alone: no turnaround at either end. Rejected at the
    # default, accepted at turnaround=0, which is what isolates the term.
    "NO_TURNAROUND": (LANCASTER, SAN_BERNARDINO, 15_000, 25_000),

    # Departs from SAN_BERNARDINO instead, a 3_000s run rather than 5_000s, so its
    # threshold is 15_400 -- and it sits at 15_400 exactly. A rule using Lancaster's
    # distance, or any fixed one, gets this pair wrong.
    "CHEAPER_DEADHEAD": (SAN_BERNARDINO, LANCASTER, 15_400, 25_000),

    # 70_000 seconds of slack, and still unreachable.
    "UNREACHABLE": (ISLAND, LAUS, 80_000, 90_000),

    # Departs 5_000s BEFORE LEAD arrives, from a station an empty run away. The
    # case a rule comparing magnitudes rather than signed times wrongly accepts.
    "OVERLAPPING": (LANCASTER, SAN_BERNARDINO, 5_000, 9_000),
}


@pytest.fixture
def synthetic(monkeypatch):
    """
    Swaps BOTH tables the predicate reads for their synthetic counterparts.

    valid_pair_deadheading resolves the schedule and the distance table in its own
    module namespace, so that is where both patches must land -- and both are
    needed: patching the schedule alone would leave the synthetic stop ids looked
    up in the real 63-stop distance table, where the LANCASTER/ISLAND key does not
    exist at all.
    """
    monkeypatch.setattr(
        preformulation, "typical_monday_trip_schedule", SYNTHETIC_SCHEDULE
    )
    monkeypatch.setattr(
        preformulation, "typical_monday_deadhead_times", SYNTHETIC_DEADHEAD_TIMES
    )


# --- the same-station branch --------------------------------------------------

def test_same_station_pair_needs_only_one_turnaround(synthetic):
    """No empty run happens, so the deadhead terms must not be charged at all."""
    assert valid_pair_deadheading("LEAD", "SAME_STATION_EXACT") is True


def test_same_station_pair_still_enforces_that_turnaround(synthetic):
    assert valid_pair_deadheading("LEAD", "SAME_STATION_SHORT") is False


def test_same_station_branch_agrees_with_valid_pair_everywhere(synthetic):
    """
    The delegation, stated as an equivalence rather than a spot check. Wherever
    the stations meet, the deadheading rule IS the no-deadheading rule; anything
    else would mean the two variants disagree about turns that involve no empty
    running, and the fleet difference between them would stop being attributable
    to deadheading.
    """
    for a, b in product(SYNTHETIC_SCHEDULE, repeat=2):
        if SYNTHETIC_SCHEDULE[a][1] == SYNTHETIC_SCHEDULE[b][0]:
            assert valid_pair_deadheading(a, b) == valid_pair(a, b), (a, b)


# --- the deadhead branch, and its exact boundary ------------------------------

def test_accepts_gap_exactly_equal_to_turnaround_plus_deadhead_plus_turnaround(synthetic):
    """The boundary is inclusive, as in valid_pair: the comparison is `<=`."""
    assert valid_pair_deadheading("LEAD", "DEADHEAD_EXACT") is True


def test_rejects_gap_one_second_below_the_boundary(synthetic):
    assert valid_pair_deadheading("LEAD", "DEADHEAD_ONE_SECOND_SHORT") is False


def test_turnaround_is_charged_at_both_ends_of_the_empty_run(synthetic):
    """
    THE test for the second turnaround. SINGLE_TURNAROUND leaves exactly enough
    time to arrive, turn once, and complete the empty run -- and not one second
    for the set to be made ready at the far end. Charging one turnaround instead
    of two accepts it, and quietly deletes a trainset from the fleet.
    """
    lead_arrival = SYNTHETIC_SCHEDULE["LEAD"][3]
    deadhead = SYNTHETIC_DEADHEAD_TIMES[frozenset([LAUS, LANCASTER])]
    assert SYNTHETIC_SCHEDULE["SINGLE_TURNAROUND"][2] == lead_arrival + TURNAROUND + deadhead
    assert valid_pair_deadheading("LEAD", "SINGLE_TURNAROUND") is False


def test_the_empty_run_itself_is_charged(synthetic):
    """
    The complement of the test above: with turnaround=0 the only term left is the
    run, and NO_TURNAROUND clears it exactly. So the boundary moves by precisely
    the two turnarounds, which is what makes the three terms additive.
    """
    assert valid_pair_deadheading("LEAD", "NO_TURNAROUND") is False
    assert valid_pair_deadheading("LEAD", "NO_TURNAROUND", turnaround=0) is True


def test_uses_the_distance_for_this_pair_of_stops(synthetic):
    """
    CHEAPER_DEADHEAD sits at 15_400, below DEADHEAD_EXACT's 17_400, and is
    accepted -- because its own empty run is 3_000s, not 5_000s. Any rule holding
    the distance fixed rejects it or accepts DEADHEAD_ONE_SECOND_SHORT.
    """
    assert valid_pair_deadheading("LEAD", "CHEAPER_DEADHEAD") is True
    assert SYNTHETIC_SCHEDULE["CHEAPER_DEADHEAD"][2] < SYNTHETIC_SCHEDULE["DEADHEAD_EXACT"][2]


def test_distance_lookup_is_symmetric(synthetic):
    """
    The table is keyed by frozenset, so an empty run costs the same in both
    directions. Stated as a test because the predicate builds that key from
    (A's arrival stop, B's departure stop) in one fixed order, and a dict keyed
    by an ordered tuple would raise KeyError on half the pairs rather than
    returning a wrong answer -- a failure that only shows up on real data.
    """
    assert valid_pair_deadheading("LEAD", "DEADHEAD_EXACT") is True
    assert SYNTHETIC_DEADHEAD_TIMES[frozenset([LAUS, LANCASTER])] == \
           SYNTHETIC_DEADHEAD_TIMES[frozenset([LANCASTER, LAUS])]


def test_rejects_a_stop_no_empty_run_can_reach(synthetic):
    """
    An infinite distance must reject on its own, at any turnaround, and without
    special-casing: `inf <= anything` is False. UNREACHABLE has 70_000s of slack,
    so time is emphatically not the obstacle.
    """
    assert valid_pair_deadheading("LEAD", "UNREACHABLE") is False
    assert valid_pair_deadheading("LEAD", "UNREACHABLE", turnaround=0) is False


def test_rejects_second_trip_departing_before_first_arrives(synthetic):
    """
    OVERLAPPING leaves Lancaster 5_000s before the set has even reached LAUS.
    Deadheading widens the arc set; it must not make it non-causal.
    """
    assert valid_pair_deadheading("LEAD", "OVERLAPPING") is False
    assert valid_pair_deadheading("LEAD", "OVERLAPPING", turnaround=0) is False


# --- structural behaviour -----------------------------------------------------

def test_default_turnaround_matches_module_constant(synthetic):
    for a, b in product(SYNTHETIC_SCHEDULE, repeat=2):
        assert valid_pair_deadheading(a, b) == \
               valid_pair_deadheading(a, b, turnaround=TURNAROUND), (a, b)


def test_returns_a_real_bool_on_both_branches(synthetic):
    """
    Both branches feed the same arc list, and the LP sums over it. The deadhead
    branch returns a comparison against a float, so this is the branch where a
    numpy scalar could creep in unnoticed.
    """
    assert isinstance(valid_pair_deadheading("LEAD", "SAME_STATION_EXACT"), bool)
    assert isinstance(valid_pair_deadheading("LEAD", "DEADHEAD_EXACT"), bool)
    assert isinstance(valid_pair_deadheading("LEAD", "UNREACHABLE"), bool)


def test_unknown_trip_id_raises_keyerror(synthetic):
    """Better a loud failure than a silently-dropped chaining opportunity."""
    with pytest.raises(KeyError):
        valid_pair_deadheading("LEAD", "NO_SUCH_TRIP")
    with pytest.raises(KeyError):
        valid_pair_deadheading("NO_SUCH_TRIP", "LEAD")


# ==========================================================================
# Properties, checked exhaustively over the real schedule
# ==========================================================================

@pytest.fixture(scope="module")
def real_schedule():
    return preformulation.typical_monday_trip_schedule


@pytest.fixture(scope="module")
def deadhead_times():
    return preformulation.typical_monday_deadhead_times


def deadhead_between(schedule, times, tripA, tripB) -> int:
    """Seconds of empty running the chaining tripA -> tripB requires. 0 in place."""
    arrival_stop, departure_stop = schedule[tripA][1], schedule[tripB][0]
    if arrival_stop == departure_stop:
        return 0
    return times[frozenset([arrival_stop, departure_stop])]


def test_deadheading_only_adds_arcs(real_schedule):
    """
    THE relationship the variant rests on. Allowing empty running can never take
    a chaining away, so valid_arcs is a subset of valid_arcs_deadheading -- which
    is what makes the deadheading fleet a LOWER bound on the no-deadheading one.
    Were it not, the four-trainset difference between 35 and 31 would not be
    attributable to deadheading at all.
    """
    assert set(valid_arcs) <= set(valid_arcs_deadheading)


def test_same_station_arcs_are_exactly_the_no_deadheading_arcs(real_schedule):
    """
    The sharper form of the subset above: deadheading adds arcs and changes none.
    Every arc the two variants share is a turn in place, and every turn in place
    is shared. An arc appearing here but not in valid_arcs would be a same-station
    pair the two rules disagree about.
    """
    in_place = {(a, b) for a, b in valid_arcs_deadheading
                if real_schedule[a][1] == real_schedule[b][0]}
    assert in_place == set(valid_arcs)


def test_arc_counts_are_stable(real_schedule):
    """
    Characterization test, in the shape the arc set actually has: 2,115 turns in
    place plus 3,201 that need an empty run, 5,316 in all. Not a spec -- a
    tripwire, so a change in the GTFS parse, the distance graph, or the chaining
    rule surfaces here with numbers to compare against rather than moving the
    fleet result silently.
    """
    in_place = sum(1 for a, b in valid_arcs_deadheading
                   if real_schedule[a][1] == real_schedule[b][0])
    assert len(valid_arcs_deadheading) == 5316
    assert in_place == 2115
    assert len(valid_arcs_deadheading) - in_place == 3201


def test_accepted_pairs_always_advance_the_clock(real_schedule):
    """
    THE critical invariant, and it survives deadheading. Every accepted chaining
    moves strictly forward in time, which is what keeps the arc set a DAG. Minimum
    path cover assumes acyclicity; with a cycle the LP can loop one 'train' through
    unlimited trips and report an absurdly low fleet with total confidence.
    """
    for a, b in valid_arcs_deadheading:
        assert real_schedule[b][2] > real_schedule[a][3], (a, b)


def test_accepted_pairs_leave_room_for_the_whole_repositioning(real_schedule, deadhead_times):
    """The rule itself, re-derived over all 5,316 arcs from the raw tables."""
    for a, b in valid_arcs_deadheading:
        gap = real_schedule[b][2] - real_schedule[a][3]
        deadhead = deadhead_between(real_schedule, deadhead_times, a, b)
        needed = TURNAROUND + deadhead + (TURNAROUND if deadhead else 0)
        assert gap >= needed, (a, b)


def test_rejected_pairs_really_do_not_fit(real_schedule, deadhead_times):
    """
    The converse sweep, over all 132^2 ordered pairs. Without it the tests above
    would all pass on an empty arc set: they constrain what IS accepted and say
    nothing about what was dropped.
    """
    rejected = 0
    for a, b in product(sorted(real_schedule), repeat=2):
        if valid_pair_deadheading(a, b):
            continue
        gap = real_schedule[b][2] - real_schedule[a][3]
        deadhead = deadhead_between(real_schedule, deadhead_times, a, b)
        needed = TURNAROUND + deadhead + (TURNAROUND if deadhead else 0)
        assert gap < needed, (a, b)
        rejected += 1
    assert rejected == 132 ** 2 - len(valid_arcs_deadheading)


def test_no_trip_ever_chains_to_itself(real_schedule):
    """Self-chaining would let one trip fill two slots and undercount the fleet."""
    for trip_id in real_schedule:
        assert valid_pair_deadheading(trip_id, trip_id) is False


def test_raising_turnaround_only_removes_pairs(real_schedule):
    """
    Monotonicity, as in the no-deadheading case but twice as sharp: the turnaround
    is charged at both ends of an empty run, so a stricter one bites harder on the
    deadhead arcs than on the turns in place. It must still only ever remove.
    """
    ids = sorted(real_schedule)
    levels = [0, 600, TURNAROUND, 1800, 2700]
    sets = [
        {(a, b) for a, b in product(ids, repeat=2)
         if valid_pair_deadheading(a, b, turnaround=t)}
        for t in levels
    ]
    for tighter, looser, t_hi, t_lo in zip(sets[1:], sets, levels[1:], levels):
        assert tighter <= looser, f"turnaround {t_hi} admitted a pair {t_lo} rejected"


def test_every_monday_stop_is_reachable_from_every_other(deadhead_times):
    """
    No infinite distance survives in the real table, so the inf branch exercised
    synthetically above never fires on this data. Worth pinning: an unreachable
    stop pair would silently delete arcs here, and would put -inf coefficients in
    the multi-depot objective (preformulation asserts on that separately).
    """
    assert all(t != float("inf") for t in deadhead_times.values())


# --- the weights the arcs carry -----------------------------------------------

def test_weights_line_up_with_the_arcs():
    """weights_and_arcs is zipped, so a length or order mismatch misprices arcs."""
    assert [arc for _, arc in weights_and_arcs] == valid_arcs_deadheading


def test_turns_in_place_are_worth_a_whole_trainset(real_schedule):
    """
    A turn in place runs no empty miles, so it saves a trainset and costs nothing:
    weight exactly 1. Any penalty here would be a cost the operation never pays.
    """
    for weight, (a, b) in weights_and_arcs:
        if real_schedule[a][1] == real_schedule[b][0]:
            assert weight == 1, (a, b)


def test_deadhead_weights_price_exactly_the_empty_run(real_schedule, deadhead_times):
    """One trainset saved, less the run's hours at the trainset-day rate."""
    for weight, (a, b) in weights_and_arcs:
        deadhead = deadhead_between(real_schedule, deadhead_times, a, b)
        expected = 1 - deadhead / 3600 * TRAINSET_DAYS_PER_DEADHEAD_HOUR
        assert weight == pytest.approx(expected), (a, b)


def test_no_arc_is_priced_below_zero():
    """
    The penalty ORDERS solutions; it must not forbid an arc. A negative weight
    would make a chaining worse than no chaining, so stage 2 would decline arcs
    stage 1 counted on -- and the two stages would disagree about the fleet.
    Break-even is ~5.9 h of empty running and the worst arc here is 4.32 h.
    """
    assert min(weight for weight, _ in weights_and_arcs) > 0
    assert max(weight for weight, _ in weights_and_arcs) == 1


# ==========================================================================
# Named cases from the real schedule
# ==========================================================================
#
# Values read straight out of typical_monday_trip_schedule and the distance
# table; the inline numbers are the actual data, so an upstream parse or graph
# change surfaces here rather than passing quietly.

def test_real_pair_that_only_deadheading_makes_possible():
    """
    200090205  (107, 161, 23940, 28320)  in at Vista Canyon (161) at 28320
    200000030  (123, 141, 40200, 45120)  out of Riverside (123) at 40200

    Different stations, so valid_pair rejects it outright. The empty run 161 -> 123
    is 9,458s, and 1200 + 9458 + 1200 = 11,858 against a gap of 11,880: it fits,
    with 22 seconds to spare. The tightest deadhead chaining in the whole arc set,
    and the one a rounding change would break first.
    """
    assert valid_pair(200090205, 200000030) is False
    assert valid_pair_deadheading(200090205, 200000030) is True


def test_real_pair_that_misses_by_twenty_nine_seconds():
    """
    295100242  (185, 107, 31260, 37860)  in at LAUS at 37860
    294100713  (184, 107, 48000, 55740)  out of Buena Park (184) at 48000

    The empty run 107 -> 184 is 7,769s; the day needs 10,169s and offers 10,140.
    The nearest miss in the data -- and the pair that shows the rule still bites:
    two and a half hours of slack is not enough when the set is in the wrong place.
    """
    assert valid_pair_deadheading(295100242, 294100713) is False


def test_that_same_pair_fits_under_a_shorter_turnaround():
    """
    The 29 seconds are turnaround, not running time: 2,371s remain after the empty
    run, so 1,185s at each end fits and 1,186s does not. Locating the miss in the
    turnaround term specifically, rather than anywhere in the sum.
    """
    assert valid_pair_deadheading(295100242, 294100713, turnaround=1185) is True
    assert valid_pair_deadheading(295100242, 294100713, turnaround=1186) is False


def test_real_pair_missed_by_a_wide_margin():
    """
    200000030  (123, 141, 40200, 45120)  in at Laguna Niguel / Mission Viejo (141)
    294100345  (185, 107, 52860, 59460)  out of San Bernardino (185) at 52860

    The 141 -> 185 run is 6,266s, so the day needs 8,666s and offers 7,740. Over
    two hours of slack and still 926s short: the deadhead term, not the boundary.
    """
    assert valid_pair_deadheading(200000030, 294100345) is False


def test_real_same_station_turn_survives_deadheading():
    """
    200000222  (161, 107, 58200, 62400)  Vista Canyon -> LAUS, in at 62400
    296200626  (107, 144, 63600, 70680)  LAUS -> Oceanside, out at 63600

    A genuine 1,200s turn at Union Station, valid in both variants and priced at a
    full trainset saved. If this ever failed, the deadheading rule would have
    started charging for an empty run of zero length.
    """
    assert valid_pair(200000222, 296200626) is True
    assert valid_pair_deadheading(200000222, 296200626) is True


def test_real_same_station_pair_with_a_long_idle_layover():
    """
    295700441  (123, 107, 14040, 19500)  Riverside -> LAUS, in at 19500
    295200235  (107, 185, 77880, 84540)  LAUS -> San Bernardino, out at 77880

    16 hours of sitting. Legal here for exactly the reason it is legal in the
    no-deadheading model: turnaround is a floor, and there is no ceiling.
    """
    assert valid_pair_deadheading(295700441, 295200235) is True


def test_real_pair_with_second_trip_departing_first():
    """
    200000026  (107, 162, 70740, 78660)  arrives Lancaster at 78660
    200090224  (162, 107, 58260, 66000)  departs Lancaster at 58260

    Same station, 20,400s backwards. Deadheading cannot help a set arrive earlier.
    """
    assert valid_pair_deadheading(200000026, 200090224) is False


def test_real_schedule_has_the_expected_shape(real_schedule):
    """
    Guards the assumption every hardcoded pair above rests on: 132 trips, each a
    4-tuple of ints, over 63 stops. If the upstream tables change shape this fails
    first and explains why the named pairs stopped making sense.
    """
    assert len(real_schedule) == 132
    assert len(preformulation.typical_monday_stops) == 63
    for trip_id, entry in real_schedule.items():
        assert isinstance(entry, tuple) and len(entry) == 4, trip_id
        assert all(isinstance(v, int) for v in entry), trip_id


# ==========================================================================
# The chains the solver actually returns
# ==========================================================================
#
# Everything above is about which chainings are LEGAL. This layer is about the
# ones zero_depot_deadheading picks: a fleet number is only worth anything if the
# arcs behind it describe days a trainset could really work. The solve happens
# once, at import of the module, so these are cheap.

@pytest.fixture(scope="module")
def solved():
    from src.solvers import zero_depot_deadheading

    return zero_depot_deadheading


@pytest.fixture(scope="module")
def trip_ids():
    from src.data_processing.typical_monday_trips import typical_monday_trip_ids

    return typical_monday_trip_ids


def test_every_chosen_arc_is_a_legal_chaining(solved):
    """
    The LP is only ever offered legal arcs, so this cannot fail without something
    upstream having gone wrong -- which is the point: it is the seam between the
    predicate this file tests and the number the repo reports.
    """
    for a, b in solved.penalised_arcs:
        assert valid_pair_deadheading(a, b), (a, b)
    for a, b in solved.unweighted_arcs:
        assert valid_pair_deadheading(a, b), (a, b)


def test_chosen_arcs_are_a_path_cover(solved, trip_ids):
    """
    At most one arc out of each trip and one into it. A trainset cannot run two
    trips at once, nor be in two places, and link_maps raises if either happens.
    Asserted before the chain walk below, which assumes exactly this.
    """
    successor, predecessor = link_maps(solved.penalised_arcs)
    assert len(successor) == len(predecessor) == len(solved.penalised_arcs)
    assert set(successor) <= set(trip_ids) and set(predecessor) <= set(trip_ids)


def test_chains_partition_the_day(solved, trip_ids):
    """
    Every trip worked exactly once, by exactly one set. A trip covered twice would
    be an over-served timetable; a trip covered by none would be a fleet number
    for a day that does not run.
    """
    built = chains(trip_ids, solved.penalised_arcs)
    covered = [trip for chain in built for trip in chain]
    assert sorted(covered) == sorted(trip_ids)
    assert len(covered) == len(set(covered)) == 132


def test_one_chain_per_trainset(solved, trip_ids):
    """
    The identity the whole formulation turns on: chains partition the trips, so
    the fleet is `len(trips) - len(arcs)`. 132 - 101 = 31.
    """
    built = chains(trip_ids, solved.penalised_arcs)
    assert len(built) == solved.penalised_fleet_size == 31
    assert len(solved.penalised_arcs) == len(trip_ids) - len(built) == 101


def test_each_chain_is_operable_end_to_end(solved, trip_ids, real_schedule, deadhead_times):
    """
    Walks each trainset's day trip by trip and checks the set can physically make
    every connection on it -- arriving, turning, repositioning if it must, and
    turning again before the next departure. Pairwise legality gives this by
    transitivity, but it is the property an operator would actually check, and it
    is stated over the diagram rather than over the arc list.
    """
    for chain in chains(trip_ids, solved.penalised_arcs):
        for a, b in zip(chain, chain[1:]):
            gap = real_schedule[b][2] - real_schedule[a][3]
            deadhead = deadhead_between(real_schedule, deadhead_times, a, b)
            assert gap >= TURNAROUND + deadhead + (TURNAROUND if deadhead else 0), (a, b)


def test_the_penalty_buys_a_cheaper_day_at_the_same_fleet(solved, real_schedule):
    """
    What weighting the arcs is FOR. Both models minimize the same fleet -- 31, by
    construction, since the unweighted model is stage 1 of the penalised one -- but
    only the penalised one then chooses among the minimum-fleet days. It runs 5
    empty moves totalling 6.15 h; the unweighted control, indifferent between them,
    runs 42. The fleet is not an artifact of the weighting; the empty mileage is.
    """
    def deadhead_moves(arcs):
        return [(a, b) for a, b in arcs if real_schedule[a][1] != real_schedule[b][0]]

    penalised = deadhead_moves(solved.penalised_arcs)
    unweighted = deadhead_moves(solved.unweighted_arcs)

    assert solved.penalised_fleet_size == solved.unweighted_fleet_size == 31
    assert len(penalised) == 5
    assert len(unweighted) == 42
    assert len(penalised) < len(unweighted)


def test_penalised_deadheading_totals_six_hours(solved, real_schedule, deadhead_times):
    """
    The census the module docstring quotes, in seconds: 22,133s, or 6h 08m 53s,
    which is the low end of the 06:08:53 - 109:56:40 range the minimum-fleet
    solutions span. Stage 2 is what makes this reproducible across CBC builds
    rather than whichever point on the optimal face the solver happened to land on.
    """
    total = sum(deadhead_between(real_schedule, deadhead_times, a, b)
                for a, b in solved.penalised_arcs)
    assert total == 22133
    assert total / 3600 == pytest.approx(6.148, abs=1e-3)
