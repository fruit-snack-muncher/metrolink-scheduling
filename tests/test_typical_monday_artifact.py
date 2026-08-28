"""Guards the one generated file that is checked in: gtfs_cleaned/typical_monday.txt.

data_collection no longer writes that file on import - regenerating it is a deliberate
`python -m src.data_processing.data_collection`. That buys pure imports, but it opens a
gap: the committed copy could drift from the GTFS tables it is derived from, and nothing
would say so. Every fleet number in this repo is computed from the trips in that file, so
a silent drift would quietly move the answers. This test is what closes the gap.

WHY THE COMPARISON IS LINE BY LINE, and not on the raw text. The repo is used with
core.autocrlf=true and carries no .gitattributes, so the committed blob is LF while the
Windows working copy is CRLF; meanwhile DataFrame.to_csv emits os.linesep, CRLF on Windows
and LF elsewhere. Each platform therefore agrees with its own checkout, and a byte-for-byte
assertion would pass here but fail for a clone whose autocrlf differs - a test failing on
line endings while the DATA is perfectly current. splitlines() drops the question entirely
and asserts the thing actually worth asserting.
"""

from src.data_processing.data_collection import OUT_PATH, typical_monday_csv

# Asserted in typical_monday_trips.py and quoted throughout the analysis, so the artifact
# holding a different number of trips would invalidate far more than this file.
TYPICAL_MONDAY_TRIPS = 132

REGENERATE = ("gtfs_cleaned/typical_monday.txt is stale; regenerate it with\n"
              "    python -m src.data_processing.data_collection")


def committed_lines() -> list[str]:
    return OUT_PATH.read_text(encoding="utf-8").splitlines()


def test_committed_artifact_matches_the_gtfs_tables():
    """The checked-in file is what today's code would generate from today's inputs."""
    assert committed_lines() == typical_monday_csv().splitlines(), REGENERATE


def test_artifact_holds_the_132_typical_monday_trips():
    """One header row plus one row per trip. Pins the number the fleet results rest on."""
    lines = committed_lines()
    assert len(lines) - 1 == TYPICAL_MONDAY_TRIPS, REGENERATE


def test_importing_data_collection_does_not_write_the_artifact():
    """The regression this file exists alongside: importing must not touch the tree.

    Re-importing is a no-op after the first import in a process, so the check that bites
    is on the module's own source - the write must sit under a __main__ guard. A plain
    mtime check would pass for the wrong reason.
    """
    import inspect

    from src.data_processing import data_collection

    source = inspect.getsource(data_collection)
    guard = source.index('if __name__ == "__main__":')
    assert source.index('open(OUT_PATH, "w"') > guard, (
        "the write to typical_monday.txt escaped the __main__ guard; importing "
        "data_collection would rewrite a tracked file again")


if __name__ == "__main__":
    # So the editor's Run button on this file runs the tests, rather than importing three
    # function definitions and exiting 0 with nothing to show for it.
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
