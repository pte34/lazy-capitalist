from datetime import UTC, datetime

from app.config import Settings


def test_reporting_distinguishes_mock_platform_signals_and_future_platform_gate(tmp_path):
    import pytest
    from fastapi import HTTPException

    from app.commands import Commands, Plan
    from app.platforms import PlatformEvent, Platforms, publication_guard
    from app.reporting import ZONE, Reporting, boundaries
    from app.store import Store
    from app.workflow import Workflow

    settings = Settings(database_path=str(tmp_path / "db"), _env_file=None)
    store = Store(settings.database_path)
    reports = Reporting(store)
    platforms = Platforms(store, reports)
    commands = Commands(store, Workflow(store), settings)
    order = commands.create(
        "Erstelle 5 Videos über aktuelle KI-Trends. Maximal CHF 3 Budget.", "report-order"
    )["id"]
    platforms.record(
        PlatformEvent(
            platform="youtube",
            channel_id="sample",
            kind="community_strike",
            source="mock_platform_signal",
            verification="mock",
            note="Synthetic test",
            occurred_at=datetime.now(UTC),
        ),
        "mock-signal",
    )
    with store.connect() as db:
        result = reports.aggregate(db, *boundaries("daily", datetime.now(ZONE).date()))
    assert result["commands"]["orders_created"] == 1
    assert result["commands"]["currency"] == "CHF"
    assert result["currency"] == "USD"
    assert result["platform_warnings"]["mock_critical_events"] == 1
    assert result["platform_warnings"]["reported_critical_events"] == 0
    assert result["real_private_uploads"] == 0
    assert result["revenue"] is result["roi"] is None
    plan = Plan(topic="Future local preview", count=1, budget_chf=3, platform="tiktok")
    commands.update(order, plan)
    commands.approve(order)
    job = commands.run(order)["videos"][0]["job_id"]
    with store.connect() as db, pytest.raises(HTTPException, match="Future platform"):
        publication_guard(db, job)
