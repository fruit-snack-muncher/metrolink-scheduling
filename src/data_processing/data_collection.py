"""
Find all regularly scheduled service and all actually active services for a 
particular day in the range of May 5, 2026 and Dec 31, 2027.
Produces a sub-Dataframe of `trips`, the pd Dataframe associated with trips.txt,
choosing only the rows corresponding to services active on that day.

Our first aim is to find such a Dataframe for a typical Monday - i.e. without
service exceptions. The resulting Dataframe is written as a CSV in .txt format
in gtfs_cleaned, named "typical_monday.txt".

All Arrow DMU trips are excluded, as they form a distinct minority of trips
operating on only the San Bernandino line. In particular, the Arrow FLIRT DMU's
are maintained exclusively out of the Arrow Maintenance Facility in San Bernandino
(https://www.gosbcta.com/maintenance-facility-construction-contract-for-future-arrow-service-trains/).
These trips have trip_short_name numbered 38xx (https://metrolinktrains.com/globalassets/schedules/timetables/2026/ml-timetable-012626-arrow.pdf).
"""

from pathlib import Path

import pandas as pd
from datetime import date

# Arrow FLIRT trip_short_name's.

ARROW_FLIRT = set([str(trip) for trip in range(3800, 3900)])

# Resolve relative to this file, not the working directory, so the reads work
# on any machine that clones the repo and from any directory the script is run
# from. This module lives in src/data_processing/, so the root is two levels up.
ROOT = Path(__file__).resolve().parents[2]
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

# Filters out all Arrow FLIRT services - trip_short_name of form 38xx.
def trips_on_day(day):
    return trips[(trips['service_id'].isin( services_active_on(day)[1] ))
                 & ~(trips['trip_short_name'].isin(ARROW_FLIRT))]

# We find Oct 19, 2026 is a "typical monday" - there is no difference in the service sets
# pre- and post- applying service exceptions.
#
# We write the resulting Dataframe to typical_monday.txt

OCT_19_2026 = date(2026, 10, 19)
assert(services_active_on(OCT_19_2026)[0] == services_active_on(OCT_19_2026)[1])

OUT_PATH = DATA_DIR / "typical_monday.txt"

# newline="" so the CSV's own "\n" line endings are never translated.
with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
    f.write(trips_on_day(OCT_19_2026).to_csv(index=False))
print(f"Wrote {OUT_PATH}")