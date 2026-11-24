"""Turn GTFS-realtime protobuf feeds into plain Python records.

Kept free of I/O so it can be tested with hand-built feeds.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from google.transit import gtfs_realtime_pb2 as rt

# TripDescriptor.ScheduleRelationship values. Numbers rather than enum names, because
# older copies of the bindings lack the newer values (DUPLICATED, DELETED).
_CANCELED = {3, 7}  # CANCELED, DELETED
_ADDED = {1, 6}  # ADDED, DUPLICATED


@dataclass(frozen=True, slots=True)
class VehiclePing:
    vehicle_id: str
    gps_ts: datetime
    lat: float
    lon: float
    bearing: float | None = None
    speed: float | None = None
    trip_id: str | None = None
    route_id: str | None = None
    service_date: date | None = None
    direction_id: int | None = None
    stop_id: str | None = None
    current_stop_sequence: int | None = None
    current_status: int | None = None


@dataclass(frozen=True, slots=True)
class TripStatusUpdate:
    service_date: date
    trip_id: str
    route_id: str | None
    status: str  # 'scheduled' | 'canceled' | 'added'
    vehicle_id: str | None


def parse_feed(content: bytes) -> rt.FeedMessage:
    feed = rt.FeedMessage()
    feed.ParseFromString(content)
    return feed


def _service_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date() if value else None
    except ValueError:
        return None


def _ts(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def parse_vehicle_positions(feed: rt.FeedMessage) -> list[VehiclePing]:
    pings = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        if not v.HasField("position"):
            continue
        pos = v.position
        if pos.latitude == 0 and pos.longitude == 0:
            continue
        vehicle_id = v.vehicle.id or entity.id
        seconds = v.timestamp or feed.header.timestamp
        if not vehicle_id or not seconds:
            continue

        trip = v.trip if v.HasField("trip") else None
        pings.append(
            VehiclePing(
                vehicle_id=vehicle_id,
                gps_ts=_ts(seconds),
                lat=pos.latitude,
                lon=pos.longitude,
                bearing=pos.bearing if pos.HasField("bearing") else None,
                speed=pos.speed if pos.HasField("speed") else None,
                trip_id=(trip.trip_id or None) if trip else None,
                route_id=(trip.route_id or None) if trip else None,
                service_date=_service_date(trip.start_date) if trip else None,
                direction_id=trip.direction_id if trip and trip.HasField("direction_id") else None,
                stop_id=v.stop_id or None,
                current_stop_sequence=(
                    v.current_stop_sequence if v.HasField("current_stop_sequence") else None
                ),
                current_status=v.current_status if v.HasField("current_status") else None,
            )
        )
    return pings


def filter_plausible(
    pings: list[VehiclePing],
    now: datetime,
    max_age: timedelta = timedelta(hours=24),
    max_future: timedelta = timedelta(hours=1),
) -> list[VehiclePing]:
    """Drop pings with clearly broken GPS clocks (they would need far-off partitions)."""
    return [p for p in pings if now - max_age <= p.gps_ts <= now + max_future]


def parse_trip_updates(feed: rt.FeedMessage) -> list[TripStatusUpdate]:
    updates = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        service_date = _service_date(tu.trip.start_date)
        if not tu.trip.trip_id or service_date is None:
            continue
        relationship = tu.trip.schedule_relationship
        if relationship in _CANCELED:
            status = "canceled"
        elif relationship in _ADDED:
            status = "added"
        else:
            status = "scheduled"
        updates.append(
            TripStatusUpdate(
                service_date=service_date,
                trip_id=tu.trip.trip_id,
                route_id=tu.trip.route_id or None,
                status=status,
                vehicle_id=tu.vehicle.id or None,
            )
        )
    return updates
