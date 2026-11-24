from datetime import UTC, date, datetime, timedelta

import pytest
from google.transit import gtfs_realtime_pb2 as rt

from app.worker.parse import (
    VehiclePing,
    filter_plausible,
    parse_feed,
    parse_trip_updates,
    parse_vehicle_positions,
)

T0 = 1794555989  # 2026-11-13 07:46:29 UTC


def vehicle_feed() -> rt.FeedMessage:
    feed = rt.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = T0 + 5

    # On a trip, with most fields set.
    e = feed.entity.add(id="21165")
    v = e.vehicle
    v.vehicle.id = "21165"
    v.position.latitude, v.position.longitude = 25.7, -80.3
    v.position.speed = 8.5
    v.timestamp = T0
    v.trip.trip_id, v.trip.route_id, v.trip.start_date = "6315472", "31120", "20261112"
    v.trip.direction_id = 0
    v.stop_id = "12015"
    v.current_stop_sequence = 100
    v.current_status = rt.VehiclePosition.IN_TRANSIT_TO

    # Not on a trip, no vehicle descriptor or timestamp: id and time fall back.
    e = feed.entity.add(id="20213")
    e.vehicle.position.latitude, e.vehicle.position.longitude = 25.8, -80.25

    # No usable position: skipped.
    e = feed.entity.add(id="bad")
    e.vehicle.vehicle.id = "bad"
    e.vehicle.position.latitude, e.vehicle.position.longitude = 0, 0
    feed.entity.add(id="no-position").vehicle.vehicle.id = "x"
    return feed


def test_parse_vehicle_positions_round_trip():
    pings = parse_vehicle_positions(parse_feed(vehicle_feed().SerializeToString()))
    assert [p.vehicle_id for p in pings] == ["21165", "20213"]

    on_trip, idle = pings
    assert on_trip.gps_ts == datetime.fromtimestamp(T0, UTC)
    assert (on_trip.lat, on_trip.lon) == pytest.approx((25.7, -80.3), abs=1e-5)  # float32
    assert on_trip.speed == 8.5 and on_trip.bearing is None
    assert (on_trip.trip_id, on_trip.route_id) == ("6315472", "31120")
    assert on_trip.service_date == date(2026, 11, 12)
    assert on_trip.direction_id == 0  # zero is a real value, not "missing"
    assert (on_trip.stop_id, on_trip.current_stop_sequence) == ("12015", 100)
    assert on_trip.current_status == rt.VehiclePosition.IN_TRANSIT_TO

    assert idle.gps_ts == datetime.fromtimestamp(T0 + 5, UTC)  # header timestamp
    assert idle.trip_id is None and idle.service_date is None and idle.direction_id is None


def test_filter_plausible_drops_broken_clocks():
    now = datetime(2026, 11, 13, 12, tzinfo=UTC)

    def ping(delta: timedelta) -> VehiclePing:
        return VehiclePing("v", now + delta, 25.0, -80.0)

    pings = [
        ping(timedelta(0)),
        ping(-timedelta(hours=23)),
        ping(-timedelta(days=2)),
        ping(timedelta(hours=2)),
    ]
    assert filter_plausible(pings, now) == pings[:2]


def test_parse_trip_updates_statuses():
    feed = rt.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    cases = [
        ("T1", rt.TripDescriptor.SCHEDULED, "21165"),
        ("T2", rt.TripDescriptor.CANCELED, ""),
        ("T3", rt.TripDescriptor.ADDED, "v9"),
    ]
    for trip_id, relationship, vehicle in cases:
        tu = feed.entity.add(id=trip_id).trip_update
        tu.trip.trip_id, tu.trip.route_id, tu.trip.start_date = trip_id, "31120", "20261113"
        tu.trip.schedule_relationship = relationship
        if vehicle:
            tu.vehicle.id = vehicle
    bad = feed.entity.add(id="bad").trip_update
    bad.trip.trip_id, bad.trip.start_date = "T4", "not-a-date"

    updates = parse_trip_updates(parse_feed(feed.SerializeToString()))
    assert [(u.trip_id, u.status, u.vehicle_id) for u in updates] == [
        ("T1", "scheduled", "21165"),
        ("T2", "canceled", None),
        ("T3", "added", "v9"),
    ]
    assert updates[0].service_date == date(2026, 11, 13)
