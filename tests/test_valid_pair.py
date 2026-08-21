"""
Tests for preformulation.valid_pair.

valid_pair(A, B, turnaround) answers one question: can a single trainset run
trip B immediately after finishing trip A? Two things have to hold.

  1. Trip A must END at the station where trip B BEGINS. A train cannot
     teleport, and deadheading is not modelled here.
  2. Trip B must depart at LEAST `turnaround` seconds after trip A arrives.
     The crew has to change ends, the set has to be serviced, and none of that
     is instant.

Formally, with A = (a_from, a_to, a_dep, a_arr) and B likewise:

    valid_pair(A, B)  <=>  a_to == b_from  and  a_arr + turnaround <= b_dep

`turnaround` is a LOWER bound, which is the subtle half. There is deliberately
no upper bound on the gap: a set that sits at Lancaster from the morning
arrival to an evening departure is a legal chain, and on the outer ends of the
AV and VC lines it is a necessary one. Capping the layover would only force the
fleet count up.

The suite is in three layers:

  * SYNTHETIC   - a hand-built schedule pinning the exact boundary around
                  `turnaround`, where the real data is too sparse to probe.
  * PROPERTIES  - exhaustive sweeps over all 132^2 real pairs, asserting the
                  invariants the fleet model depends on. These are the tests
                  that actually protect the result.
  * REAL PAIRS  - named cases from the GTFS data, as readable anchors.
"""

from itertools import product

import pytest

import preformulation
from preformulation import TURNAROUND, valid_pair

# Real Metrolink stop_ids, used here purely as distinguishable labels.
LAUS = 107  # L.A. Union Station
LANCASTER = 162
SAN_BERNARDINO = 185


# ==========================================================================
# Synthetic schedule: the boundary around `turnaround`
# ==========================================================================

# Every trip is the 4-tuple valid_pair expects:
#     (departure stop_id, arrival stop_id, departure time, arrival time)
# with times in seconds past midnight.
#
# LEAD is the anchor: it ends at LAUS at t=10_000. Every follower is placed
# relative to that arrival to isolate exactly one behaviour.
SYNTHETIC_SCHEDULE = {
    "LEAD": (LANCASTER, LAUS, 0, 10_000),

    # Starts at LAUS, departs long after LEAD arrives. Comfortably chainable.
    "AMPLE": (LAUS, LANCASTER, 40_000, 50_000),

    # Departs exactly TURNAROUND after LEAD arrives -- the boundary itself,
    # which must be ACCEPTED: 20 minutes is enough, by definition.
    "EXACT": (LAUS, LANCASTER, 10_000 + TURNAROUND, 20_000),

    # One second inside the boundary. Must be rejected.
    "ONE_SECOND_SHORT": (LAUS, LANCASTER, 10_000 + TURNAROUND - 1, 20_000),

    # Departs the instant LEAD arrives. No time to turn the set at all.
    "ZERO_GAP": (LAUS, LANCASTER, 10_000, 20_000),

    # Departs BEFORE LEAD arrives -- the train is still 5_000 seconds out.
    # This is the case an upper-bound comparison wrongly accepts.
    "OVERLAPPING": (LAUS, LANCASTER, 5_000, 9_000),

    # Plenty of time, but starts at the wrong station entirely.
    "WRONG_STATION": (SAN_BERNARDINO, LAUS, 40_000, 50_000),
}


@pytest.fixture
def synthetic(monkeypatch):
    """
    Swaps the GTFS-derived schedule for SYNTHETIC_SCHEDULE.

    valid_pair resolves the dict in its own module namespace (it was pulled in
    with `from typical_monday_trips import ...`), so that is where the patch
    must land. monkeypatch restores the original after each test.
    """
    monkeypatch.setattr(
        preformulation, "typical_monday_trip_schedule", SYNTHETIC_SCHEDULE
    )


# --- the station requirement ----------------------------------------------

def test_chains_when_stations_meet_and_time_is_ample(synthetic):
    assert valid_pair("LEAD", "AMPLE") is True


def test_rejects_wrong_station_despite_ample_time(synthetic):
    """Time is not the obstacle: WRONG_STATION departs 30_000s after LEAD lands."""
    assert valid_pair("LEAD", "WRONG_STATION") is False


def test_wrong_station_rejected_even_at_zero_turnaround(synthetic):
    """turnaround=0 relaxes the timing rule entirely; geography still binds."""
    assert valid_pair("LEAD", "WRONG_STATION", turnaround=0) is False


# --- the turnaround requirement, and its exact boundary -------------------

def test_accepts_gap_exactly_equal_to_turnaround(synthetic):
    """
    A gap of exactly `turnaround` is sufficient -- the comparison is `<=`, not
    `<`. This matters in practice: real Metrolink turns cluster on round
    numbers, and 21 real pairs sit at exactly 1200s.
    """
    assert valid_pair("LEAD", "EXACT") is True


def test_rejects_gap_one_second_below_turnaround(synthetic):
    assert valid_pair("LEAD", "ONE_SECOND_SHORT") is False


def test_rejects_zero_gap(synthetic):
    """Departing the moment the inbound arrives leaves no time to turn the set."""
    assert valid_pair("LEAD", "ZERO_GAP") is False


def test_rejects_second_trip_departing_before_first_arrives(synthetic):
    """
    The train is still 5_000 seconds from LAUS when OVERLAPPING is due to leave
    it. Treating `turnaround` as an upper bound accepts this, which is how a
    fleet count silently comes out too low.
    """
    assert valid_pair("LEAD", "OVERLAPPING") is False


def test_turnaround_is_a_lower_bound_not_an_upper_one(synthetic):
    """
    The distinction the whole model rests on. AMPLE idles 30_000s -- 25x the
    required turnaround -- and must still chain. A rule capping the gap would
    reject it and inflate the fleet count.
    """
    gap = SYNTHETIC_SCHEDULE["AMPLE"][2] - SYNTHETIC_SCHEDULE["LEAD"][3]
    assert gap > TURNAROUND * 20
    assert valid_pair("LEAD", "AMPLE") is True


# --- the turnaround parameter itself --------------------------------------

def test_zero_turnaround_accepts_zero_gap(synthetic):
    """With turnaround=0 an instantaneous turn is legal, so ZERO_GAP flips."""
    assert valid_pair("LEAD", "ZERO_GAP", turnaround=0) is True


def test_zero_turnaround_still_rejects_overlap(synthetic):
    """Even at turnaround=0, B cannot depart before A has arrived."""
    assert valid_pair("LEAD", "OVERLAPPING", turnaround=0) is False


def test_one_second_over_the_boundary_flips_a_valid_pair(synthetic):
    """EXACT clears 1200s exactly, so requiring 1201s must reject it."""
    assert valid_pair("LEAD", "EXACT", turnaround=TURNAROUND) is True
    assert valid_pair("LEAD", "EXACT", turnaround=TURNAROUND + 1) is False


def test_generous_turnaround_leaves_only_ample(synthetic):
    """A 3-hour turnaround leaves only the 30_000s gap standing."""
    three_hours = 3 * 3600
    assert valid_pair("LEAD", "AMPLE", turnaround=three_hours) is True
    assert valid_pair("LEAD", "EXACT", turnaround=three_hours) is False


def test_default_turnaround_matches_module_constant(synthetic):
    """Calling with no turnaround must equal calling with TURNAROUND."""
    for a, b in product(SYNTHETIC_SCHEDULE, repeat=2):
        assert valid_pair(a, b) == valid_pair(a, b, turnaround=TURNAROUND)


# --- structural behaviour -------------------------------------------------

def test_order_matters(synthetic):
    """
    Chaining is directional, and the matching step depends on that asymmetry.
    LEAD -> AMPLE is valid; reversed, AMPLE arrives at 50_000, long after LEAD
    departed at 0.
    """
    assert valid_pair("LEAD", "AMPLE") is True
    assert valid_pair("AMPLE", "LEAD") is False


def test_returns_a_real_bool(synthetic):
    """
    The fleet count sums these results, so a numpy scalar or None would corrupt
    it quietly. The `is True` / `is False` assertions above already enforce
    this; this states the requirement outright.
    """
    assert isinstance(valid_pair("LEAD", "AMPLE"), bool)
    assert isinstance(valid_pair("LEAD", "WRONG_STATION"), bool)


def test_unknown_trip_id_raises_keyerror(synthetic):
    """Better a loud failure than a silently-dropped chaining opportunity."""
    with pytest.raises(KeyError):
        valid_pair("LEAD", "NO_SUCH_TRIP")
    with pytest.raises(KeyError):
        valid_pair("NO_SUCH_TRIP", "LEAD")


# ==========================================================================
# Properties, checked exhaustively over the real schedule
# ==========================================================================
#
# These sweep all 132^2 = 17,424 ordered pairs. Spot checks can miss a sign
# error that only bites on a handful of pairs; these cannot. They are also the
# invariants the min-fleet computation actually relies on, so a regression here
# means a wrong answer, not just a wrong test.

@pytest.fixture(scope="module")
def real_schedule():
    return preformulation.typical_monday_trip_schedule


@pytest.fixture(scope="module")
def accepted(real_schedule):
    """Every ordered pair the default turnaround accepts."""
    return [
        (a, b)
        for a, b in product(sorted(real_schedule), repeat=2)
        if valid_pair(a, b)
    ]


def test_accepted_pairs_always_advance_the_clock(accepted, real_schedule):
    """
    THE critical invariant. Every accepted chain must move strictly forward in
    time, because that is what makes the arc set a DAG -- no sequence of chains
    can return to where it started. Minimum path cover assumes acyclicity; with
    a cycle the LP can loop one 'train' through unlimited trips and report an
    absurdly low fleet with total confidence.
    """
    for a, b in accepted:
        assert real_schedule[b][2] > real_schedule[a][3], (a, b)


def test_accepted_pairs_always_share_a_station(accepted, real_schedule):
    for a, b in accepted:
        assert real_schedule[a][1] == real_schedule[b][0], (a, b)


def test_no_trip_ever_chains_to_itself(real_schedule):
    """Self-chaining would let one trip fill two slots and undercount the fleet."""
    for trip_id in real_schedule:
        assert valid_pair(trip_id, trip_id) is False


def test_gap_never_falls_below_turnaround(accepted, real_schedule):
    for a, b in accepted:
        assert real_schedule[b][2] - real_schedule[a][3] >= TURNAROUND, (a, b)


def test_raising_turnaround_only_removes_pairs(real_schedule):
    """
    Monotonicity: a stricter turnaround can never CREATE a chaining
    opportunity. This is what makes the fleet count a lower bound that tightens
    as the operating assumptions get more conservative -- if it were violated,
    the sensitivity sweep would be meaningless.
    """
    ids = sorted(real_schedule)
    levels = [0, 600, TURNAROUND, 1800, 2700]
    sets = [
        {(a, b) for a, b in product(ids, repeat=2) if valid_pair(a, b, turnaround=t)}
        for t in levels
    ]
    for tighter, looser, t_hi, t_lo in zip(sets[1:], sets, levels[1:], levels):
        assert tighter <= looser, f"turnaround {t_hi} admitted a pair {t_lo} rejected"


def test_rejects_every_pair_that_runs_backwards(real_schedule):
    """
    Direct sweep of the failure mode: any pair whose stations match but whose
    departure precedes the arrival must be rejected, no matter how generous the
    turnaround. At turnaround=0 the timing rule is at its weakest, so this is
    the hardest version of the check.
    """
    checked = 0
    for a, b in product(sorted(real_schedule), repeat=2):
        A, B = real_schedule[a], real_schedule[b]
        if A[1] == B[0] and B[2] < A[3]:
            assert valid_pair(a, b) is False, (a, b)
            assert valid_pair(a, b, turnaround=0) is False, (a, b)
            checked += 1
    # Guards the guard: if the data or parse changed such that no pair looks
    # like this, the loop above would pass by being empty.
    assert checked > 0, "no backwards-running pairs found -- is the fixture stale?"


def test_arc_count_is_stable(accepted):
    """
    Characterization test. 2,115 arcs at a 20-minute turnaround over the
    132-trip typical Monday. Not a spec -- a tripwire, so that a change in the
    GTFS parse or the chaining rule surfaces here with a number to compare
    against rather than silently shifting the fleet result downstream.
    """
    assert len(accepted) == 2115


# ==========================================================================
# Named cases from the real schedule
# ==========================================================================
#
# Values read straight out of typical_monday_trip_schedule; the inline tuples
# are the actual data, so an upstream parse change surfaces here rather than
# passing quietly.

def test_real_pair_at_exact_twenty_minute_turn():
    """
    200000222  (161, 107, 58200, 62400)  Vista Canyon -> LAUS, in at 62400
    296200626  (107, 144, 63600, 70680)  LAUS -> Oceanside, out at 63600

    A gap of 1200s to the second -- a genuine tight turn at Union Station.
    """
    assert valid_pair(200000222, 296200626) is True


def test_real_pair_nineteen_minutes_is_too_tight():
    """
    Same inbound train, a different LAUS departure:
    294400189  (107, 162, 63540, 71460)  out at 63540, a 1140s gap.

    Sixty seconds short of the standard, so it must be rejected.
    """
    assert valid_pair(200000222, 294400189) is False


def test_real_pair_nineteen_minutes_passes_under_a_relaxed_turnaround():
    """The same pair becomes legal if 15 minutes is deemed enough."""
    assert valid_pair(200000222, 294400189, turnaround=900) is True


def test_real_pair_with_a_long_idle_layover():
    """
    295700441  (123, 107, 14040, 19500)  Riverside -> LAUS, in at 19500
    295200235  (107, 185, 77880, 84540)  LAUS -> San Bernardino, out at 77880

    A 58,380s gap -- the set sits for over 16 hours, the longest layover any
    accepted pair carries. Legal, if idle: turnaround is a floor, not a ceiling.
    """
    assert valid_pair(295700441, 295200235) is True


def test_real_pair_with_second_trip_departing_first():
    """
    200000026  (107, 162, 70740, 78660)  arrives Lancaster at 78660
    200090224  (162, 107, 58260, 66000)  departs Lancaster at 58260

    Stations line up, but the departure is 20,400s BEFORE the arrival -- two
    different trains passing through Lancaster hours apart.
    """
    assert valid_pair(200000026, 200090224) is False


def test_real_pair_at_different_stations():
    """
    200000030  (123, 141, 40200, 45120)  ends Laguna Niguel / Mission Viejo (141)
    294100345  (185, 107, 52860, 59460)  starts San Bernardino (185)

    A little over two hours of slack, but the stations differ, so no chain.
    """
    assert valid_pair(200000030, 294100345) is False


def test_real_schedule_has_the_expected_shape(real_schedule):
    """
    Guards the assumption the fixtures above rest on: 132 trips, each a 4-tuple
    of ints. If typical_monday_trips.py changes shape, this fails first and
    explains why the hardcoded pairs stopped making sense.
    """
    assert len(real_schedule) == 132
    for trip_id, entry in real_schedule.items():
        assert isinstance(entry, tuple) and len(entry) == 4, trip_id
        assert all(isinstance(v, int) for v in entry), trip_id
