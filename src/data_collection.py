"""
Find all regularly scheduled service and all actually active services for a 
particular day in the range of May 5, 2026 and Dec 31, 2027.
Produces a sub-Dataframe of `trips`, the pd Dataframe associated with trips.txt,
choosing only the rows corresponding to services active on that day.

Our first aim is to find such a Dataframe for a typical Monday - i.e. without
service exceptions. The resulting Dataframe is written as a CSV in .txt format
in gtfs_cleaned, named "typical_monday.txt".
"""

from pathlib import Path

import pandas as pd
from datetime import date

# Resolve relative to this file, not the working directory, so the reads work
# on any machine that clones the repo and from any directory the script is run
# from. This module lives in src/, so the repo root is one level up.
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "gtfs_cleaned"

cal = pd.read_csv(DATA_DIR / "calendar.txt", dtype=str)
cal_dates = pd.read_csv(DATA_DIR / "calendar_dates.txt", dtype=str)
routes = pd.read_csv(DATA_DIR / "routes.txt", dtype=str)
stop_times = pd.read_csv(DATA_DIR / "stop_times.txt", dtype=str)
stops = pd.read_csv(DATA_DIR / "stops.txt", dtype=str)
trips = pd.read_csv(DATA_DIR / "trips.txt", dtype=str)

# Returns service_id's of regular services running on a particular day.
# Returns service_id's before and applying exceptions.
def services_active_on(day: date) -> set:
    DOW = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    key = day.strftime("%Y%m%d")
    target_weekday = DOW[day.weekday()] # Returns the day of week as a string.

    # Sub-dataframe of cal containing all services running (normally) on day, 
    # excluding discontinued services.
    all_services = cal[(cal[target_weekday] == "1") & (cal.start_date <= key) & (cal.end_date >= key)]

    # Set of all services in all_services. active_today will be filtered for exceptions.
    all_today, active_today = set(all_services.service_id), set(all_services.service_id)
    # Contains service exceptions for this day. May be empty!
    today_services = cal_dates[cal_dates.date == key]

    # Add all services of exception type 1 (additional service exception)
    active_today |= set(today_services.loc[today_services.exception_type == "1", "service_id"])
    # Remove all services of exception type 2 (no service exception)
    active_today -= set(today_services.loc[today_services.exception_type == "2", "service_id"])

    return all_today, active_today

def trips_on_day(day):
    return trips[trips.service_id.isin( services_active_on(day)[1] )]

# We find Oct 19, 2026 is a "typical monday" - there is no difference in the service sets
# pre- and post- applying service exceptions.
# 
# If it is not already written, we write the resulting Dataframe to typical_monday.txt

OCT_19_2026 = date(2026, 10, 19)
assert(services_active_on(OCT_19_2026)[0] == services_active_on(OCT_19_2026)[1])

OUT_PATH = DATA_DIR / "typical_monday.txt"

# newline="" everywhere so the CSV's own "\n" line endings are never translated,
# making the write and the read-back comparison byte-for-byte consistent.
def write_if_changed(df: pd.DataFrame, path: Path) -> bool:
    new_csv = df.to_csv(index=False)

    if path.exists():
        with open(path, "r", newline="", encoding="utf-8") as f:
            if f.read() == new_csv:
                return False  # Already up to date - leave the file alone.

    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(new_csv)
    return True

if write_if_changed(trips_on_day(OCT_19_2026), OUT_PATH):
    print(f"Wrote {OUT_PATH}")
else:
    print(f"{OUT_PATH} already up to date")