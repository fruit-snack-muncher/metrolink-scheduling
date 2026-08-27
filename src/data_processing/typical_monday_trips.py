"""
Re-writes the data for a typical Monday schedule in a format convenient for
formulating a LP. Every trip is represented as a key in a dictionary, with
value a tuple (departure stop_id, arrival stop_id, departure time, arrival time).
Such information is necessary for determining whether trips can chain into
each other.

Since this relies on typical_monday.txt for trips, we naturally exclude the
Arrow trips as well. This results in a total 132 trips on a typical Monday, as
demonstrated in the number of non-label non-empty lines in typical_monday.txt
(easily verifiable by inspection).
"""

from pathlib import Path

import pandas as pd

# src/data_processing/ is two levels below the repo root, where the GTFS tables live.
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "gtfs_cleaned"

stop_times = pd.read_csv(DATA_DIR / "stop_times.txt")
stops = pd.read_csv(DATA_DIR / "stops.txt")
trips = pd.read_csv(DATA_DIR / "trips.txt")

typical_monday = pd.read_csv(DATA_DIR / "typical_monday.txt")
typical_monday_trip_ids = typical_monday.trip_id.tolist()
typical_monday_trip_schedule = {}

# returns the sub-DataFrame of stop_times with only the given trip_id's, inputted
# as a set of integers.
def stop_times_for_trips(trip_ids: set[int]) -> pd.DataFrame:
    filtered_stop_times = stop_times[stop_times.trip_id.isin(trip_ids)]
    return filtered_stop_times

typical_stops = stop_times_for_trips(typical_monday_trip_ids)

# For a trip with some trip_id, inputs the following information into typical_monday_trip_schedule:
# trip_id: departure stop_id, arrival stop_id, departure time, arrival time.
# All times are in seconds past 00:00:00.
def typical_schedule_per_trip(trip_id: int) -> None:
    if trip_id in typical_monday_trip_schedule.keys():
        return

    trip_stop_times = typical_stops[typical_stops.trip_id == trip_id]
    trips, _ = trip_stop_times.shape

    # Turn a tuple (hours, minutes, seconds) into the total number of seconds as an integer.
    time_eval = lambda x: 3600*x[0] + 60*x[1] + x[2]

    departure, arrival = trip_stop_times.iloc[0], trip_stop_times.iloc[trips-1]
    departure_stop, arrival_stop = int(departure.stop_id), int(arrival.stop_id)

    # converts each string HH:MM:SS into an int, by splitting hours/minutes/seconds and
    # applying arithmetic as per time_eval.
    departure_time = time_eval(list( map(int, departure.departure_time.split(':')) ))
    arrival_time = time_eval(list( map(int, arrival.arrival_time.split(':')) ))

    typical_monday_trip_schedule[trip_id] = (departure_stop,arrival_stop,departure_time,arrival_time)
    return

for trip in typical_monday_trip_ids:
    typical_schedule_per_trip(trip)

# The typical Monday contains 132 total trips.
assert( len(typical_monday_trip_schedule.keys()) == 132 )

if __name__ == "__main__":
    # One line per trip rather than one dict repr, so the output can be read,
    # grepped, or diffed. Hours are not capped at 24: GTFS expresses a trip that
    # runs past midnight as e.g. 25:10:00, and the seconds count preserves that.
    def hhmmss(seconds: int) -> str:
        return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

    print(f"{len(typical_monday_trip_schedule)} trips on the typical Monday")
    for trip_id, (dep_stop, arr_stop, dep_time, arr_time) in sorted(typical_monday_trip_schedule.items()):
        print(f"{trip_id}  stop {dep_stop:>3} -> {arr_stop:>3}   {hhmmss(dep_time)} -> {hhmmss(arr_time)}")