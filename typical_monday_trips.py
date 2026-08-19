from pathlib import Path

import pandas as pd
from datetime import date

DATA_DIR = Path(__file__).resolve().parent / "gtfs_cleaned"

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

if __name__ == "__main__":
    print(typical_monday_trip_schedule)


