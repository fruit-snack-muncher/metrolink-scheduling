"""Minimum fleet with deadheading allowed, penalised and unpenalised.

A set may reposition empty between trips. Both models below run over the *same*
arc set and differ only in what an arc is worth, which is why they live in one
file: the comparison between them is the point, and neither is readable without
the other.

PENALISED weighs each arc by one trainset saved less the cost of the empty run,
so the LP prefers the cheaper of two equally short fleets. UNWEIGHTED gives every
arc a flat 1, making empty running free; it is the control, and it answers one
question - whether 31 is an artifact of the weighting.

Under the two-stage solver in min_path_cover the relationship is tighter than a
comparison. The unweighted model *is* stage 1: it fixes the minimum fleet and
stops, with nothing to choose between the solutions that achieve it. The
penalised model is that same stage 1 followed by a stage 2 that picks the
cheapest of them. So the two share their fleet size by construction, and differ
only in whether anything decides which minimum-fleet day gets run.

Reported on by analysis/fleet/zero_depot_deadheading_report.py and
analysis/fleet/zero_depot_deadheading_UNWEIGHTED_report.py.
"""

from src.data_processing.preformulation import weights_and_arcs
from src.data_processing.typical_monday_trips import typical_monday_trip_ids
from src.solvers.min_path_cover import solve

unweighted_weights_and_arcs = [(1, arc) for _, arc in weights_and_arcs]

penalised = solve(typical_monday_trip_ids, weights_and_arcs)
penalised_fleet_size, penalised_arcs = penalised.fleet_size, penalised.arcs

unweighted = solve(typical_monday_trip_ids, unweighted_weights_and_arcs)
unweighted_fleet_size, unweighted_arcs = unweighted.fleet_size, unweighted.arcs

# 31 trainsets - four fewer than without deadheading. Equal by construction, since
# both are stage 1 of the same problem, so the fleet size is not an artifact of the
# weighting. What the penalty buys is visible only in the deadhead census.
assert penalised_fleet_size == 31
assert unweighted_fleet_size == penalised_fleet_size
