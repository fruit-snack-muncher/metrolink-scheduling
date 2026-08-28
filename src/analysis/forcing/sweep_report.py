"""What the forcing sweeps found: the cost of mandating or forbidding any one variable.

analysis/forcing/forcing_sweep.py re-solves every problem once per decision variable per value and
records the result. This reads those CSVs back and answers the questions they were run to
answer - is any single forcing infeasible, which ones cost a trainset, and how often a
forcing keeps the minimum fleet while losing the variant's own optimum.

Reads the CSVs and NOTHING ELSE. No solver is imported and no LP is built, so this is a
seconds-long command that can be re-run freely against a finished sweep. Every number in the
report is therefore reproducible from files in the repo, not from a solver run whose
composition depends on the CBC build that produced it.
"""

from collections import Counter

from src.analysis.forcing.forcing_sweep import (PROBLEM_NAMES, SWEEPS, completed, expected_points,
                                        rows_on_disk)
from src.analysis.markdown_report import REPORTS, write_report

TITLE = "The cost of forcing a single decision"
SUMMARY = ("Every chaining, depot departure and depot arrival re-solved twice - once forbidden, "
           "once mandated - across all four models. 47,814 forced re-solves, none infeasible.")

# Uniform arc weights mean min_path_cover skips stage 2, so these two have no objective to
# reach beyond the chaining count itself. Their objective column restates the fleet column.
UNIFORM_WEIGHT_PROBLEMS = ["zero_depot", "deadheading_unweighted"]


def load() -> dict[str, list[dict]]:
    """Every sweep's rows, refusing to report on a sweep that has not finished.

    Partial data would still produce a plausible-looking table, which is the failure worth
    preventing: a report that silently describes 40% of the points is worse than no report.
    """
    sweeps = {}
    for name in PROBLEM_NAMES:
        rows = rows_on_disk(SWEEPS / f"{name}.csv")
        total = expected_points(name)
        if len(completed(SWEEPS / f"{name}.csv")) < total:
            raise SystemExit(
                f"{name} has {len(rows)} of {total} points; the sweeps must finish first.\n"
                f"    python -m src.analysis.forcing.forcing_sweep --status\n"
                f"    python -m src.analysis.forcing.forcing_sweep --problem {name}")
        sweeps[name] = rows
    return sweeps


def coverage(sweeps) -> str:
    lines = ["COVERAGE AND INTEGRITY", ""]
    lines.append(f"  {'problem':<24}{'rows':>8}{'expected':>10}{'distinct':>10}{'blank fields':>14}")
    for name, rows in sweeps.items():
        blank = sum(1 for row in rows
                    for field in ("family", "variable", "forced_value", "status")
                    if not row[field])
        lines.append(f"  {name:<24}{len(rows):>8}{expected_points(name):>10}"
                     f"{len(completed(SWEEPS / f'{name}.csv')):>10}{blank:>14}")
    return "\n".join(lines)


def feasibility(sweeps) -> str:
    """Whether any single forcing can make the schedule impossible."""
    statuses = Counter(row["status"] for rows in sweeps.values() for row in rows)
    total = sum(statuses.values())
    lines = ["FEASIBILITY", "",
             f"  {total} forced re-solves in total"]
    for status, count in statuses.most_common():
        lines.append(f"    {status:<12}{count:>8}")

    # The headline finding, and worth failing loudly on rather than quietly reporting: the
    # schedule has enough slack that no ONE move is impossible to require or to ban.
    assert set(statuses) == {"Optimal"}, f"a forcing was not Optimal: {dict(statuses)}"
    lines.append("")
    lines.append("  No single forcing makes any model infeasible.")
    return "\n".join(lines)


def cost_of_a_forcing(sweeps) -> str:
    """Forbidding a move against mandating one - the asymmetry is the point."""
    lines = ["COST OF A FORCING", "",
             "  'costs a set' = still solvable, but no longer at the minimum fleet.", "",
             f"  {'problem':<24}{'forced':>8}{'points':>9}{'min fleet kept':>16}{'costs a set':>14}"]
    for name, rows in sweeps.items():
        for value in ("0", "1"):
            sub = [row for row in rows if row["forced_value"] == value]
            kept = sum(row["min_fleet_reachable"] == "True" for row in sub)
            label = "forbid" if value == "0" else "mandate"
            lines.append(f"  {name:<24}{label:>8}{len(sub):>9}{kept:>16}{len(sub) - kept:>14}")
    return "\n".join(lines)


def fleet_sizes(sweeps) -> str:
    """Which fleet sizes a forced problem can land on."""
    lines = ["FLEET SIZES REACHED", "",
             "  A forcing that costs anything costs exactly one trainset, never more.", "",
             f"  {'problem':<24}fleet: points reached at it"]
    for name, rows in sweeps.items():
        counts = Counter(int(row["fleet_size"]) for row in rows)
        spread = "".join(f"{size}: {counts[size]:<8}" for size in sorted(counts))
        lines.append(f"  {name:<24}{spread}".rstrip())

        # The prose above is the claim; this is the check. Anything beyond {n, n+1} would mean
        # a single forcing cost two trainsets, which is a different finding entirely.
        reached = sorted(counts)
        assert reached in ([reached[0]], [reached[0], reached[0] + 1]), \
            f"{name} reached fleet sizes {reached}, not a minimum and at most one more"
    return "\n".join(lines)


def objective_versus_fleet(sweeps) -> str:
    """Forcings that keep the fleet but lose the optimum - the planner's real margin.

    Split by direction, because that is where the whole asymmetry lives: forbidding a move
    rarely disturbs the optimum, while mandating one usually does.
    """
    lines = ["OBJECTIVE VERSUS FLEET", "",
             "  A forcing can be free in trainsets and still pay in deadhead positioning.", "",
             f"  {'problem':<24}{'forced':>8}{'min fleet kept':>16}{'and optimal':>13}"
             f"{'fleet but not optimal':>23}"]
    for name, rows in sweeps.items():
        for value in ("0", "1"):
            kept = [row for row in rows
                    if row["forced_value"] == value and row["min_fleet_reachable"] == "True"]
            optimal = sum(row["objective_reachable"] == "True" for row in kept)
            label = "forbid" if value == "0" else "mandate"
            lines.append(f"  {name:<24}{label:>8}{len(kept):>16}{optimal:>13}"
                         f"{len(kept) - optimal:>23}")

    lines.append("")
    lines.append("  The two uniform-weight models have no objective of their own: with every arc")
    lines.append("  weighted alike, stage 2 is skipped and the objective column restates the fleet")
    lines.append("  column. Verified here rather than asserted in prose -")
    for name in UNIFORM_WEIGHT_PROBLEMS:
        identical = all(row["objective_reachable"] == row["min_fleet_reachable"]
                        for row in sweeps[name])
        lines.append(f"    {name:<24}columns identical: {identical}")
        assert identical, f"{name} has uniform weights, so its two columns must agree"
    return "\n".join(lines)


def critical_arcs(sweeps) -> str:
    """The arcs a model cannot do without: forbidding one costs a trainset."""
    lines = ["CRITICAL ARCS", "",
             "  Chainings whose FORBIDDING costs a trainset - the moves the schedule leans on.", ""]
    for name, rows in sweeps.items():
        critical = [row for row in rows
                    if row["forced_value"] == "0" and row["min_fleet_reachable"] != "True"]
        lines.append(f"  {name} - {len(critical)} critical of "
                     f"{sum(1 for row in rows if row['forced_value'] == '0')}")
        for row in critical:
            lines.append(f"    {row['family']:<10}{row['variable']:<34}"
                         f"fleet {row['fleet_size']} without it")
        if not critical:
            lines.append("    none: every single move can be banned and the fleet still met")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


if __name__ == "__main__":
    sweeps = load()
    body = "\n\n\n".join([coverage(sweeps), feasibility(sweeps), cost_of_a_forcing(sweeps),
                          fleet_sizes(sweeps), objective_versus_fleet(sweeps),
                          critical_arcs(sweeps)])
    print(f"Wrote {write_report(REPORTS / 'sweeps.md', TITLE, SUMMARY, 'src.analysis.forcing.sweep_report', body)}")
