import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from db import engine

app = FastAPI(title="Health Monitor API")


# =========================
# Pydantic models
# =========================

class EventCreate(BaseModel):
    event_type: str
    event_timestamp: datetime
    title: str
    note: str | None = None
    severity: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None


class EventUpdate(BaseModel):
    event_type: str | None = None
    event_timestamp: datetime | None = None
    title: str | None = None
    note: str | None = None
    severity: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None


class SettingsUpdate(BaseModel):
    low_red_max: int | None = None
    low_yellow_max: int | None = None
    green_min: int | None = None
    green_max: int | None = None
    high_yellow_max: int | None = None
    default_graph_hours: int | None = None
    units: str | None = None
    time_format: str | None = None


# =========================
# Helpers
# =========================

VALID_EVENT_TYPES = {
    "Meal",
    "Stress",
    "Drive",
    "Exercise",
    "Bad sleep",
    "Felt bad",
    "Medication / supplement",
    "Custom",
}


def row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def iso_or_none(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def serialize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    return iso_or_none(value)


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: serialize_value(v) for k, v in row.items()}


def get_settings_row() -> dict[str, Any]:
    query = text("""
        select
            id,
            low_red_max,
            low_yellow_max,
            green_min,
            green_max,
            high_yellow_max,
            default_graph_hours,
            units,
            time_format,
            created_at,
            updated_at
        from settings
        limit 1
    """)

    with engine.connect() as connection:
        row = connection.execute(query).mappings().first()

    if not row:
        raise HTTPException(status_code=500, detail="Settings row not found.")

    return dict(row)


def classify_glucose(value: int | None, settings: dict[str, Any]) -> str | None:
    if value is None:
        return None

    low_red_max = settings["low_red_max"]
    low_yellow_max = settings["low_yellow_max"]
    green_min = settings["green_min"]
    green_max = settings["green_max"]
    high_yellow_max = settings["high_yellow_max"]

    if value <= low_red_max:
        return "red_low"
    if value <= low_yellow_max:
        return "yellow_low"
    if green_min <= value <= green_max:
        return "green"
    if value <= high_yellow_max:
        return "yellow_high"
    return "red_high"


def build_glucose_summary(
    readings: list[dict[str, Any]],
    settings: dict[str, Any],
    events_count: int,
) -> dict[str, Any]:
    if not readings:
        return {
            "current_glucose": None,
            "average_glucose": None,
            "high": None,
            "low": None,
            "time_in_green_minutes": 0,
            "time_in_yellow_minutes": 0,
            "time_in_red_minutes": 0,
            "event_count": events_count,
            "red_low_count": 0,
            "red_high_count": 0,
        }

    values = [r["glucose_value"] for r in readings if r["glucose_value"] is not None]
    if not values:
        return {
            "current_glucose": None,
            "average_glucose": None,
            "high": None,
            "low": None,
            "time_in_green_minutes": 0,
            "time_in_yellow_minutes": 0,
            "time_in_red_minutes": 0,
            "event_count": events_count,
            "red_low_count": 0,
            "red_high_count": 0,
        }

    green_count = 0
    yellow_count = 0
    red_count = 0
    red_low_count = 0
    red_high_count = 0

    for reading in readings:
        category = classify_glucose(reading["glucose_value"], settings)
        if category == "green":
            green_count += 1
        elif category in {"yellow_low", "yellow_high"}:
            yellow_count += 1
        elif category == "red_low":
            red_count += 1
            red_low_count += 1
        elif category == "red_high":
            red_count += 1
            red_high_count += 1

    # Approximate 5 minutes per CGM reading
    return {
        "current_glucose": readings[-1]["glucose_value"],
        "average_glucose": round(sum(values) / len(values), 1),
        "high": max(values),
        "low": min(values),
        "time_in_green_minutes": green_count * 5,
        "time_in_yellow_minutes": yellow_count * 5,
        "time_in_red_minutes": red_count * 5,
        "event_count": events_count,
        "red_low_count": red_low_count,
        "red_high_count": red_high_count,
    }


def get_glucose_readings_between(start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
    query = text("""
        select
            id,
            reading_timestamp,
            glucose_value,
            units,
            trend_direction,
            trend_description,
            trend_arrow,
            source,
            fetched_at,
            created_at
        from glucose_readings
        where reading_timestamp >= :start_dt
          and reading_timestamp < :end_dt
        order by reading_timestamp asc
    """)

    with engine.connect() as connection:
        rows = connection.execute(
            query,
            {"start_dt": start_dt, "end_dt": end_dt}
        ).mappings().all()

    return [dict(r) for r in rows]


def get_event_count_between(start_dt: datetime, end_dt: datetime) -> int:
    query = text("""
        select count(*) as count
        from events
        where event_timestamp >= :start_dt
          and event_timestamp < :end_dt
    """)

    with engine.connect() as connection:
        row = connection.execute(
            query,
            {"start_dt": start_dt, "end_dt": end_dt}
        ).mappings().first()

    return int(row["count"]) if row else 0


# =========================
# Health routes
# =========================

@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def database_health_check() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("select 1"))

    return {"status": "ok", "database": "connected"}


# =========================
# Glucose routes
# =========================

@app.get("/glucose/latest")
def get_latest_glucose() -> dict[str, Any]:
    query = text("""
        select
            id,
            reading_timestamp,
            glucose_value,
            units,
            trend_direction,
            trend_description,
            trend_arrow,
            source,
            fetched_at,
            created_at
        from glucose_readings
        order by reading_timestamp desc
        limit 1
    """)

    with engine.connect() as connection:
        row = connection.execute(query).mappings().first()

    if not row:
        return {
            "status": "ok",
            "data": None,
            "message": "No glucose readings found yet."
        }

    return {
        "status": "ok",
        "data": serialize_row(dict(row))
    }


@app.get("/glucose/history")
def get_glucose_history(
    hours: int = Query(default=12, ge=1, le=168)
) -> dict[str, Any]:
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=hours)

    readings = get_glucose_readings_between(start_dt, end_dt)

    return {
        "status": "ok",
        "hours": hours,
        "count": len(readings),
        "data": [serialize_row(r) for r in readings],
    }


@app.get("/glucose/daily-summary")
def get_daily_summary(
    target_date: date | None = None
) -> dict[str, Any]:
    settings = get_settings_row()

    if target_date is None:
        target_date = date.today()

    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    readings = get_glucose_readings_between(start_dt, end_dt)
    event_count = get_event_count_between(start_dt, end_dt)

    summary = build_glucose_summary(readings, settings, event_count)

    return {
        "status": "ok",
        "date": target_date.isoformat(),
        "summary": summary,
    }


@app.get("/glucose/weekly-summary")
def get_weekly_summary(
    end_date: date | None = None
) -> dict[str, Any]:
    settings = get_settings_row()

    if end_date is None:
        end_date = date.today()

    start_date = end_date - timedelta(days=6)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    readings = get_glucose_readings_between(start_dt, end_dt)
    event_count = get_event_count_between(start_dt, end_dt)

    overall_summary = build_glucose_summary(readings, settings, event_count)

    day_by_day: list[dict[str, Any]] = []
    for i in range(7):
        current_day = start_date + timedelta(days=i)
        day_start = datetime.combine(current_day, datetime.min.time())
        day_end = day_start + timedelta(days=1)

        day_readings = [r for r in readings if day_start <= r["reading_timestamp"] < day_end]
        day_event_count = get_event_count_between(day_start, day_end)
        day_summary = build_glucose_summary(day_readings, settings, day_event_count)

        day_by_day.append({
            "date": current_day.isoformat(),
            **day_summary,
        })

    return {
        "status": "ok",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summary": {
            "seven_day_average": overall_summary["average_glucose"],
            "seven_day_high": overall_summary["high"],
            "seven_day_low": overall_summary["low"],
            "time_in_green_minutes": overall_summary["time_in_green_minutes"],
            "time_in_yellow_minutes": overall_summary["time_in_yellow_minutes"],
            "time_in_red_minutes": overall_summary["time_in_red_minutes"],
            "weekly_event_count": overall_summary["event_count"],
            "day_by_day": day_by_day,
        },
    }


# =========================
# Event routes
# =========================

@app.get("/events")
def get_events(
    limit: int = Query(default=50, ge=1, le=500)
) -> dict[str, Any]:
    query = text("""
        select
            id,
            event_type,
            event_timestamp,
            title,
            note,
            severity,
            tags,
            created_at,
            updated_at
        from events
        order by event_timestamp desc
        limit :limit
    """)

    with engine.connect() as connection:
        rows = connection.execute(query, {"limit": limit}).mappings().all()

    return {
        "status": "ok",
        "count": len(rows),
        "data": [serialize_row(dict(r)) for r in rows],
    }


@app.post("/events")
def create_event(payload: EventCreate) -> dict[str, Any]:
    if payload.event_type not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid event_type.")

    insert_query = text("""
        insert into events (
            event_type,
            event_timestamp,
            title,
            note,
            severity,
            tags
        )
        values (
            :event_type,
            :event_timestamp,
            :title,
            :note,
            :severity,
            cast(:tags as jsonb)
        )
        returning
            id,
            event_type,
            event_timestamp,
            title,
            note,
            severity,
            tags,
            created_at,
            updated_at
    """)

    with engine.begin() as connection:
        row = connection.execute(
            insert_query,
            {
                "event_type": payload.event_type,
                "event_timestamp": payload.event_timestamp,
                "title": payload.title,
                "note": payload.note,
                "severity": payload.severity,
                "tags": json.dumps(payload.tags) if payload.tags is not None else None,
            }
        ).mappings().first()

    return {
        "status": "ok",
        "data": serialize_row(dict(row)),
    }


@app.patch("/events/{event_id}")
def update_event(event_id: str, payload: EventUpdate) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    if "event_type" in updates and updates["event_type"] not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid event_type.")

    set_clauses = []
    params: dict[str, Any] = {"event_id": event_id}

    for key, value in updates.items():
        if key == "tags":
            set_clauses.append("tags = cast(:tags as jsonb)")
            params["tags"] = json.dumps(value) if value is not None else None
        else:
            set_clauses.append(f"{key} = :{key}")
            params[key] = value

    query = text(f"""
        update events
        set {", ".join(set_clauses)}
        where id = :event_id
        returning
            id,
            event_type,
            event_timestamp,
            title,
            note,
            severity,
            tags,
            created_at,
            updated_at
    """)

    with engine.begin() as connection:
        row = connection.execute(query, params).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Event not found.")

    return {
        "status": "ok",
        "data": serialize_row(dict(row)),
    }


@app.delete("/events/{event_id}")
def delete_event(event_id: str) -> dict[str, Any]:
    query = text("""
        delete from events
        where id = :event_id
        returning id
    """)

    with engine.begin() as connection:
        row = connection.execute(query, {"event_id": event_id}).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Event not found.")

    return {
        "status": "ok",
        "deleted_id": str(row["id"]),
    }


# =========================
# Settings routes
# =========================

@app.get("/settings")
def get_settings() -> dict[str, Any]:
    row = get_settings_row()
    return {
        "status": "ok",
        "data": serialize_row(row),
    }


@app.patch("/settings")
def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update.")

    current = get_settings_row()
    candidate = {**current, **updates}

    if not (
        candidate["low_red_max"] < candidate["low_yellow_max"] < candidate["green_min"]
        and candidate["green_min"] <= candidate["green_max"] < candidate["high_yellow_max"]
    ):
        raise HTTPException(status_code=400, detail="Settings thresholds are out of order.")

    if candidate["default_graph_hours"] not in {3, 6, 12, 24}:
        raise HTTPException(status_code=400, detail="default_graph_hours must be 3, 6, 12, or 24.")

    if candidate["units"] != "mg/dL":
        raise HTTPException(status_code=400, detail="Only mg/dL is supported right now.")

    if candidate["time_format"] not in {"12h", "24h"}:
        raise HTTPException(status_code=400, detail="time_format must be '12h' or '24h'.")

    set_clauses = []
    params: dict[str, Any] = {"id": current["id"]}

    for key, value in updates.items():
        set_clauses.append(f"{key} = :{key}")
        params[key] = value

    query = text(f"""
        update settings
        set {", ".join(set_clauses)}
        where id = :id
        returning
            id,
            low_red_max,
            low_yellow_max,
            green_min,
            green_max,
            high_yellow_max,
            default_graph_hours,
            units,
            time_format,
            created_at,
            updated_at
    """)

    with engine.begin() as connection:
        row = connection.execute(query, params).mappings().first()

    return {
        "status": "ok",
        "data": serialize_row(dict(row)),
    }


# =========================
# System route
# =========================

@app.get("/sync-status")
def get_sync_status() -> dict[str, Any]:
    query = text("""
        select
            id,
            run_started_at,
            run_finished_at,
            status,
            readings_pulled,
            new_readings_saved,
            error_message,
            created_at
        from sync_runs
        order by run_started_at desc
        limit 1
    """)

    with engine.connect() as connection:
        row = connection.execute(query).mappings().first()

    if not row:
        return {
            "status": "ok",
            "data": None,
            "message": "No sync runs found yet."
        }

    return {
        "status": "ok",
        "data": serialize_row(dict(row)),
    }