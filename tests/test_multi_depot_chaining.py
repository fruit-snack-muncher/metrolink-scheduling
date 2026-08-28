"""
Tests for the chainings multi_depot returns: deadheading allowed, home depots enforced.

The zero-depot models let a trainset materialize wherever its first trip happens
to start and vanish wherever its last one ends. This one does not. Every set is
drawn from an overnight depot in the morning, works a chain of trips, and is
returned to a depot at night - and it must be returned to the SAME depot it came
from, at a facility with a finite number of stalls.

That single addition is what these tests are about, because it is not visible in
the arc list. `Solution.arcs` from multi_depot looks exactly like `Solution.arcs`
from zero_depot_deadheading; the depot label lives in `chained_arcs`,
`home_depots` and `terminal_depots`, and the property that matters is a statement
about whole CHAINS rather than about any one arc:

    every arc on a trainset's day carries that trainset's depot label, and the
    depot it is returned to at night is the depot it was drawn from that morning.

Nothing in the arc list can express that, so nothing in a test over the arc list
can check it. The chains have to be rebuilt and walked, which is what most of this
file does.

The suite runs in four layers:

  * THE CHAININGS  - the arcs are still legal deadheading chainings, and still a
                     path cover. The depot rows must not have invented a turn.
  * THE DEPOTS     - the home-depot property itself, walked chain by chain, plus
                     capacity and the balance between morning and night.
  * THE COST       - what enforcing home depots is worth: nothing in trainsets,
                     something in empty miles.
  * FORCING        - the same invariants under a pinned variable, and the
                     infeasibilities that show the constraint is load-bearing
                     rather than merely satisfied by the unforced optimum.

The unforced baseline is solved once, at import of multi_depot, so the first three
layers are free. The forcing layer re-solves, at roughly a second per case.
"""

from collections import Counter

import pytest

from src.data_processing.preformulation import (
    OVERNIGHT_CAPACITIES,
    OVERNIGHT_DEPOTS,
    TURNAROUND,
    typical_monday_deadhead_times,
    valid_arcs_deadheading,
    valid_pair_deadheading,
)
from src.data_processing.typical_monday_trips import (
    typical_monday_trip_ids,
    typical_monday_trip_schedule,
)
from src.solvers import multi_depot
from tests.chain_checks import chains, link_maps

CMF = 107   # L.A. Union Station / Central Maintenance Facility, 30 stalls
EMF = 185   # San Bernardino Downtown / Eastern Maintenance Facility, 7 stalls

FLEET_SIZE = 31
CHAININGS = 101


@pytest.fixture(scope="module")
def baseline():
    """The unforced solution, already solved at import. Never mutated here."""
    return multi_depot.baseline


@pytest.fixture(scope="module")
def built(baseline):
    """The baseline's arcs as trainset diagrams: 31 chains covering all 132 trips."""
    return chains(typical_monday_trip_ids, baseline.arcs)


def deadhead_between(tripA, tripB) -> int:
    """Seconds of empty running the chaining tripA -> tripB requires. 0 in place."""
    arrival_stop = typical_monday_trip_schedule[tripA][1]
    departure_stop = typical_monday_trip_schedule[tripB][0]
    if arrival_stop == departure_stop:
        return 0
    return typical_monday_deadhead_times[frozenset([arrival_stop, departure_stop])]


def depot_of_chain(baseline, chain) -> int:
    """The depot label the whole chain is supposed to carry, read off its first trip."""
    return baseline.home_depots[chain[0]]


# ==========================================================================
# The chainings themselves
# ==========================================================================
#
# The depot rows narrow the feasible region; they must not widen the arc set. If
# the model ever chained two trips no trainset could actually connect, the fleet
# number would be for a day that cannot be operated - and the depot labels would
# be decorating a fiction.

def test_the_baseline_solved(baseline):
    """Unforced, both stages are always Optimal; anything else voids the rest."""
    assert baseline.status == "Optimal"


def test_every_chosen_arc_is_a_legal_deadheading_chaining(baseline):
    for a, b in baseline.arcs:
        assert valid_pair_deadheading(a, b), (a, b)


def test_chosen_arcs_come_from_the_offered_arc_set(baseline):
    """
    Stronger than legality, and the seam worth guarding: multi_depot builds its
    variables from multi_weights_and_arcs, which is valid_arcs_deadheading
    replicated once per depot. An arc outside that set would mean the depot
    labelling had introduced a chaining the preformulation never sanctioned.
    """
    assert set(baseline.arcs) <= set(valid_arcs_deadheading)


def test_no_arc_is_used_twice(baseline):
    """
    The same chaining is a separate variable for each depot, so the same bare arc
    could in principle be selected under two labels. The flow-requirement rows
    forbid it; here it is, checked on the returned solution.
    """
    assert len(baseline.arcs) == len(set(baseline.arcs)) == CHAININGS
    assert len(baseline.chained_arcs) == CHAININGS


def test_chosen_arcs_are_a_path_cover(baseline):
    """
    At most one arc out of each trip and one into it - a trainset cannot run two
    trips at once, nor be in two places. link_maps raises if either happens, and
    everything below depends on it holding.
    """
    successor, predecessor = link_maps(baseline.arcs)
    assert len(successor) == len(predecessor) == CHAININGS
    assert set(successor) <= set(typical_monday_trip_ids)
    assert set(predecessor) <= set(typical_monday_trip_ids)


def test_chains_partition_the_day(built):
    """Every trip worked exactly once, by exactly one set."""
    covered = [trip for chain in built for trip in chain]
    assert sorted(covered) == sorted(typical_monday_trip_ids)
    assert len(covered) == len(set(covered)) == 132


def test_one_chain_per_trainset(baseline, built):
    """132 trips less 101 chainings is 31 trainsets, and the solver agrees."""
    assert len(built) == baseline.fleet_size == FLEET_SIZE
    assert baseline.chained == CHAININGS
    assert baseline.fleet_size == len(typical_monday_trip_ids) - baseline.chained


def test_each_chain_is_operable_end_to_end(built):
    """
    Walks each trainset's day and checks it can make every connection on it:
    arrive, turn, reposition empty if it must, turn again, depart. The property an
    operator would check, stated over the diagram rather than over the arc list.
    """
    for chain in built:
        for a, b in zip(chain, chain[1:]):
            gap = typical_monday_trip_schedule[b][2] - typical_monday_trip_schedule[a][3]
            deadhead = deadhead_between(a, b)
            assert gap >= TURNAROUND + deadhead + (TURNAROUND if deadhead else 0), (a, b)


# ==========================================================================
# The home depots
# ==========================================================================

def test_home_depots_are_exactly_the_chain_starts(baseline, built):
    """
    A depot departure is what OPENS a chain, which is why counting them counts the
    fleet. So the trips with a home depot must be precisely the trips no arc
    enters -- if a trip mid-chain carried a home depot, a set would be drawn from a
    depot onto a trip another set is already working through.
    """
    assert set(baseline.home_depots) == {chain[0] for chain in built}
    assert len(baseline.home_depots) == FLEET_SIZE


def test_terminal_depots_are_exactly_the_chain_ends(baseline, built):
    assert set(baseline.terminal_depots) == {chain[-1] for chain in built}
    assert len(baseline.terminal_depots) == FLEET_SIZE


def test_every_arc_on_a_chain_carries_that_chains_depot(baseline, built):
    """
    THE property this model adds, and the reason the chains have to be rebuilt to
    see it. Per-depot flow conservation is supposed to carry one label along a
    whole chain; a chain that changed label mid-day would be two half-days handed
    to one trainset, and the depot accounting below would be counting nothing.
    """
    label = {arc: depot for depot, arc in baseline.chained_arcs}
    assert len(label) == CHAININGS, "an arc appears under two depot labels"

    for chain in built:
        depot = depot_of_chain(baseline, chain)
        for arc in zip(chain, chain[1:]):
            assert label[arc] == depot, (chain[0], arc, label[arc], depot)


def test_every_set_is_returned_to_the_depot_it_came_from(baseline, built):
    """
    Depot faithfulness, at the level it actually means something. The aggregate row
    in the model only balances COUNTS per depot -- 24 out, 24 back -- which a
    solution could satisfy by swapping two sets between facilities overnight. This
    checks the individual set, end of chain against start of chain.
    """
    for chain in built:
        assert baseline.terminal_depots[chain[-1]] == depot_of_chain(baseline, chain), chain


def test_each_trip_belongs_to_exactly_one_depot(baseline, built):
    """
    The consequence of the two tests above, stated as the fact an operator cares
    about: every trip on the timetable is worked by a set homed at one identifiable
    facility, and the 132 assignments cover the day with nothing double-claimed.
    """
    depot_of_trip = {}
    for chain in built:
        depot = depot_of_chain(baseline, chain)
        for trip in chain:
            assert trip not in depot_of_trip
            depot_of_trip[trip] = depot
    assert sorted(depot_of_trip) == sorted(typical_monday_trip_ids)
    assert set(depot_of_trip.values()) <= set(OVERNIGHT_DEPOTS)


def test_no_depot_exceeds_its_capacity(baseline):
    """A facility cannot stable more sets overnight than it has room for."""
    for depot, capacity in zip(OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES):
        assert baseline.depot_fleet_sizes[depot] <= capacity, depot


def test_the_depot_fleets_sum_to_the_fleet(baseline):
    """
    Every set is stabled somewhere, and nowhere twice. Guards against a fleet size
    counted one way and a per-depot split counted another.
    """
    assert sum(baseline.depot_fleet_sizes.values()) == baseline.fleet_size == FLEET_SIZE


def test_the_depot_split_matches_what_the_chains_show(baseline, built):
    """
    depot_fleet_sizes is read off the solver's departure variables; the chains are
    rebuilt from the arcs. Two independent routes to the same numbers, so a
    mismatch would mean the reported split describes a different solution from the
    one the arcs encode.
    """
    from_chains = Counter(depot_of_chain(baseline, chain) for chain in built)
    assert dict(from_chains) == {d: n for d, n in baseline.depot_fleet_sizes.items() if n}


def test_morning_and_night_balance_at_each_depot(baseline):
    """
    Depot faithfulness in its aggregate form: as many sets return to a facility as
    left it, so the stabling is repeatable the next day rather than draining one
    depot into another.
    """
    departures = Counter(baseline.home_depots.values())
    arrivals = Counter(baseline.terminal_depots.values())
    assert departures == arrivals


def test_the_depot_split_is_stable(baseline):
    """
    Characterization test: 24 sets out of the CMF at LAUS, 7 out of the EMF at San
    Bernardino, and the EMF full to its 7 stalls. Not a spec -- a tripwire. The
    split is chosen by stage 2 among the minimum-fleet solutions, so it is
    reproducible, but it would move if a capacity, a depot, or the deadhead rate
    changed, and this is where that surfaces with a number to compare against.
    """
    assert baseline.depot_fleet_sizes == {CMF: 24, EMF: 7}
    assert baseline.depot_fleet_sizes[EMF] == dict(zip(OVERNIGHT_DEPOTS, OVERNIGHT_CAPACITIES))[EMF]


# ==========================================================================
# What enforcing home depots costs
# ==========================================================================

def test_home_depots_cost_no_trainsets(baseline):
    """
    The headline comparison. Requiring every set to start and end its day at one
    facility, within capacity, does NOT increase the fleet: 31 either way. So the
    31 reported by the zero-depot deadheading model survives contact with a
    constraint the zero-depot model simply ignored, and is not an artifact of
    letting trainsets appear from nowhere.
    """
    from src.solvers import zero_depot_deadheading

    assert baseline.fleet_size == zero_depot_deadheading.penalised_fleet_size == FLEET_SIZE


def test_home_depots_are_paid_for_in_empty_miles(baseline):
    """
    What they cost instead. Positioning sets to and from their home facilities
    leaves the chains themselves less free, so the day runs 7 empty moves between
    trips where the zero-depot model runs 5. A cost in mileage, not in fleet --
    which is the finding, and the reason both models are kept.
    """
    from src.solvers import zero_depot_deadheading

    def deadhead_moves(arcs):
        return [(a, b) for a, b in arcs if deadhead_between(a, b)]

    assert len(deadhead_moves(baseline.arcs)) == 7
    assert len(deadhead_moves(zero_depot_deadheading.penalised_arcs)) == 5


def test_the_flow_cost_optimum_is_stable(baseline):
    """
    Stage 2's objective at the returned solution: chainings, less every empty mile
    run between trips and to and from the depots. A tripwire on the whole
    weighting, and the baseline every forced run in analysis/forcing/forcing_sweep.py is
    compared against -- if this moves, every finding in that sweep moves with it.
    """
    assert baseline.objective == pytest.approx(87.6314833, abs=1e-6)


# ==========================================================================
# The same invariants under forcing
# ==========================================================================
#
# Everything above is one solution. These re-solve with a variable pinned, which
# is both a check that the invariants are structural rather than incidental to the
# unforced optimum, and the mechanism analysis/forcing/forcing_sweep.py is built on.
#
# The infeasibility cases are the sharper half. A constraint that is satisfied by
# every solution anyone looks at might not be doing any work at all; the way to
# show it is load-bearing is to ask for something it forbids and be refused.

# 200000222 (161, 107, 58200, 62400) -> 296200626 (107, 144, 63600, 70680): a real
# same-station turn at LAUS, used here purely as a variable that certainly exists.
TURN_AT_LAUS = (200000222, 296200626)


def test_a_chain_forced_out_of_the_far_depot_still_holds_together():
    """
    Pins one trip to be drawn from San Bernardino, whatever the optimum preferred,
    and re-checks the whole home-depot story on the solution that comes back. The
    invariants above are properties of the formulation, so they must survive a
    solution nobody optimized for.
    """
    forced = multi_depot.solve(forced_departures={(EMF, TURN_AT_LAUS[0]): 1})
    assert forced.status == "Optimal"
    assert forced.home_depots[TURN_AT_LAUS[0]] == EMF

    built = chains(typical_monday_trip_ids, forced.arcs)
    label = {arc: depot for depot, arc in forced.chained_arcs}
    for chain in built:
        depot = forced.home_depots[chain[0]]
        assert forced.terminal_depots[chain[-1]] == depot, chain
        for arc in zip(chain, chain[1:]):
            assert label[arc] == depot, (chain[0], arc)
        for a, b in zip(chain, chain[1:]):
            assert valid_pair_deadheading(a, b), (a, b)

    assert len(built) == forced.fleet_size
    assert sorted(t for chain in built for t in chain) == sorted(typical_monday_trip_ids)


def test_one_trip_cannot_be_drawn_from_two_depots():
    """
    Each trip takes exactly one unit of inflow, so mandating two depot departures
    onto the same trip has no solution. Without this row a trip could be worked by
    two sets at once and the fleet would count in an arbitrary unit.
    """
    forced = multi_depot.solve(forced_departures={(CMF, TURN_AT_LAUS[0]): 1,
                                                  (EMF, TURN_AT_LAUS[0]): 1})
    assert forced.status == "Infeasible"


def test_a_set_cannot_be_stabled_where_it_did_not_start():
    """
    THE test that home depots are enforced rather than merely observed. The trip is
    mandated to open a chain drawn from LAUS and to close one returned to San
    Bernardino. Every count in the model still balances -- one departure, one
    arrival, both within capacity -- and it is per-depot flow conservation alone
    that refuses it. Remove that block and this solve succeeds, which is exactly
    the failure test_every_set_is_returned_to_the_depot_it_came_from would then
    have to catch on its own.
    """
    forced = multi_depot.solve(forced_departures={(CMF, TURN_AT_LAUS[0]): 1},
                               forced_arrivals={(EMF, TURN_AT_LAUS[0]): 1})
    assert forced.status == "Infeasible"


def test_a_chaining_cannot_join_two_differently_homed_sets():
    """
    The same refusal one step along a chain. The arc is mandated under the San
    Bernardino label while its second trip is mandated to be drawn fresh from LAUS,
    so one trip would be entered both by a chaining and by a depot departure. It is
    the label, not the geometry, that makes this impossible: the arc alone solves
    fine, and so does the departure alone.
    """
    assert multi_depot.solve(
        forced_chainings={(EMF, TURN_AT_LAUS): 1}).status == "Optimal"
    assert multi_depot.solve(
        forced_departures={(CMF, TURN_AT_LAUS[1]): 1}).status == "Optimal"
    assert multi_depot.solve(
        forced_chainings={(EMF, TURN_AT_LAUS): 1},
        forced_departures={(CMF, TURN_AT_LAUS[1]): 1}).status == "Infeasible"


def test_forcing_an_unknown_variable_raises_rather_than_solving():
    """
    A key naming no variable would otherwise be a forcing silently never applied,
    and a sweep that reported 'the fleet survives forbidding this arc' about an arc
    it never touched. Loud failure is the right one.
    """
    with pytest.raises(KeyError):
        multi_depot.solve(forced_chainings={(EMF, (1, 2)): 1})
    with pytest.raises(KeyError):
        multi_depot.solve(forced_departures={(EMF, 1): 1})
    with pytest.raises(KeyError):
        multi_depot.solve(forced_arrivals={(999, TURN_AT_LAUS[0]): 1})
