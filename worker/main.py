import json
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from pydexcom import Dexcom
from sqlalchemy import create_engine, text


load_dotenv()

DEXCOM_USERNAME = os.getenv("DEXCOM_USERNAME", "").strip()
DEXCOM_PASSWORD = os.getenv("DEXCOM_PASSWORD", "").strip()
DEXCOM_REGION = os.getenv("DEXCOM_REGION", "us").strip().lower()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))
HISTORY_WINDOW_MINUTES = int(os.getenv("HISTORY_WINDOW_MINUTES", "180"))
HISTORY_MAX_COUNT = int(os.getenv("HISTORY_MAX_COUNT", "36"))

if not DEXCOM_USERNAME or not DEXCOM_PASSWORD:
    raise ValueError("DEXCOM_USERNAME and DEXCOM_PASSWORD must be set in worker .env")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL must be set in worker .env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def normalize_reading(reading: object, fetched_at: datetime) -> dict[str, Any]:
    raw_json = getattr(reading, "json", {}) or {}

    timestamp = None
    for attr in ("datetime", "time"):
        value = getattr(reading, attr, None)
        if value is not None:
            timestamp = value
            break

    return {
        "reading_timestamp": timestamp,
        "glucose_value": getattr(reading, "value", None),
        "units": "mg/dL",
        "trend_direction": getattr(reading, "trend_direction", None),
        "trend_description": getattr(reading, "trend_description", None),
        "trend_arrow": getattr(reading, "trend_arrow", None),
        "source": "Dexcom Share",
        "fetched_at": fetched_at,
        "raw_payload": raw_json,
    }


def get_existing_timestamps(
    readings: list[dict[str, Any]]
) -> set[datetime]:
    timestamps = [r["reading_timestamp"] for r in readings if r["reading_timestamp"] is not None]
    if not timestamps:
        return set()

    query = text("""
        select reading_timestamp
        from glucose_readings
        where reading_timestamp = any(:timestamps)
    """)

    with engine.connect() as connection:
        rows = connection.execute(query, {"timestamps": timestamps}).mappings().all()

    return {row["reading_timestamp"] for row in rows}


def insert_glucose_readings(readings: list[dict[str, Any]]) -> int:
    if not readings:
        return 0

    insert_query = text("""
        insert into glucose_readings (
            reading_timestamp,
            glucose_value,
            units,
            trend_direction,
            trend_description,
            trend_arrow,
            source,
            fetched_at,
            raw_payload
        )
        values (
            :reading_timestamp,
            :glucose_value,
            :units,
            :trend_direction,
            :trend_description,
            :trend_arrow,
            :source,
            :fetched_at,
            cast(:raw_payload as jsonb)
        )
        on conflict (source, reading_timestamp) do nothing
    """)

    inserted = 0
    with engine.begin() as connection:
        for reading in readings:
            result = connection.execute(
                insert_query,
                {
                    "reading_timestamp": reading["reading_timestamp"],
                    "glucose_value": reading["glucose_value"],
                    "units": reading["units"],
                    "trend_direction": reading["trend_direction"],
                    "trend_description": reading["trend_description"],
                    "trend_arrow": reading["trend_arrow"],
                    "source": reading["source"],
                    "fetched_at": reading["fetched_at"],
                    "raw_payload": json.dumps(reading["raw_payload"]),
                },
            )
            inserted += result.rowcount or 0

    return inserted


def create_sync_run(started_at: datetime) -> str:
    query = text("""
        insert into sync_runs (
            run_started_at,
            status,
            readings_pulled,
            new_readings_saved
        )
        values (
            :run_started_at,
            'running',
            0,
            0
        )
        returning id
    """)

    with engine.begin() as connection:
        row = connection.execute(query, {"run_started_at": started_at}).mappings().first()

    return str(row["id"])


def finish_sync_run(
    sync_run_id: str,
    *,
    status: str,
    readings_pulled: int,
    new_readings_saved: int,
    error_message: str | None = None,
) -> None:
    query = text("""
        update sync_runs
        set
            run_finished_at = :run_finished_at,
            status = :status,
            readings_pulled = :readings_pulled,
            new_readings_saved = :new_readings_saved,
            error_message = :error_message
        where id = :sync_run_id
    """)

    with engine.begin() as connection:
        connection.execute(
            query,
            {
                "run_finished_at": datetime.now().astimezone(),
                "status": status,
                "readings_pulled": readings_pulled,
                "new_readings_saved": new_readings_saved,
                "error_message": error_message,
                "sync_run_id": sync_run_id,
            },
        )


def determine_status(
    *,
    readings_pulled: int,
    new_readings_saved: int,
    latest_age_minutes: float | None,
) -> str:
    if readings_pulled == 0:
        return "empty"

    if latest_age_minutes is None:
        return "partial"

    if latest_age_minutes > 20:
        return "stale"

    return "success"


def run_sync_cycle() -> None:
    started_at = datetime.now().astimezone()
    sync_run_id = create_sync_run(started_at)

    try:
        dexcom = Dexcom(
            username=DEXCOM_USERNAME,
            password=DEXCOM_PASSWORD,
            region=DEXCOM_REGION,
        )

        fetched_at = datetime.now().astimezone()
        raw_readings = dexcom.get_glucose_readings(
            minutes=HISTORY_WINDOW_MINUTES,
            max_count=HISTORY_MAX_COUNT,
        )

        normalized_readings = [
            normalize_reading(reading, fetched_at=fetched_at)
            for reading in raw_readings
        ]
        normalized_readings = [
            reading for reading in normalized_readings
            if reading["reading_timestamp"] is not None
        ]
        normalized_readings.sort(key=lambda r: r["reading_timestamp"])

        readings_pulled = len(normalized_readings)

        if readings_pulled == 0:
            finish_sync_run(
                sync_run_id,
                status="empty",
                readings_pulled=0,
                new_readings_saved=0,
                error_message=None,
            )
            print("Sync complete: no readings returned.")
            return

        existing_timestamps = get_existing_timestamps(normalized_readings)
        new_readings = [
            reading
            for reading in normalized_readings
            if reading["reading_timestamp"] not in existing_timestamps
        ]

        new_readings_saved = insert_glucose_readings(new_readings)

        latest_timestamp = normalized_readings[-1]["reading_timestamp"]
        latest_age_minutes = round(
            (fetched_at - latest_timestamp).total_seconds() / 60.0,
            2,
        )

        status = determine_status(
            readings_pulled=readings_pulled,
            new_readings_saved=new_readings_saved,
            latest_age_minutes=latest_age_minutes,
        )

        finish_sync_run(
            sync_run_id,
            status=status,
            readings_pulled=readings_pulled,
            new_readings_saved=new_readings_saved,
            error_message=None,
        )

        print(
            f"Sync complete: status={status}, "
            f"readings_pulled={readings_pulled}, "
            f"new_readings_saved={new_readings_saved}, "
            f"latest_age_minutes={latest_age_minutes}"
        )

    except Exception as exc:
        finish_sync_run(
            sync_run_id,
            status="failed",
            readings_pulled=0,
            new_readings_saved=0,
            error_message=str(exc),
        )
        raise


if __name__ == "__main__":
    run_sync_cycle()