from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from trek.api import app, KILL_SWITCH_CHANNEL
from trek.db import get_session
from backend.app.models.enums import StrategyStatus


class FakeResult:
    def __init__(self, rows: list):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeSessionContext:
    """Mimics `async with session.begin():` context manager."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


def make_fake_session(killed_ids: list[uuid.UUID] | None = None):
    session = AsyncMock()

    if killed_ids is None:
        killed_ids = []

    rows = [(uid,) for uid in killed_ids]
    call_count = 0

    async def fake_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeResult(rows)
        return MagicMock()

    session.execute = fake_execute
    session.begin = lambda: FakeSessionContext(session)
    return session


@pytest.fixture
def two_live_ids():
    return [uuid.uuid4(), uuid.uuid4()]


@pytest.fixture
def client():
    return TestClient(app)


class TestKillSwitchEndpoint:
    def test_kills_live_strategies_and_returns_count(self, client, two_live_ids):
        session = make_fake_session(killed_ids=two_live_ids)
        app.dependency_overrides[get_session] = lambda: session
        try:
            resp = client.post(
                "/api/kill-switch",
                json={"reason": "emergency", "triggered_by": "user"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["strategies_affected"] == 2
            assert data["triggered_by"] == "user"
            assert data["reason"] == "emergency"
            assert len(data["details"]["killed_ids"]) == 2
        finally:
            app.dependency_overrides.clear()

    def test_idempotent_when_nothing_live(self, client):
        session = make_fake_session(killed_ids=[])
        app.dependency_overrides[get_session] = lambda: session
        try:
            resp = client.post(
                "/api/kill-switch",
                json={"reason": "just checking"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["strategies_affected"] == 0
            assert data["details"]["killed_ids"] == []
        finally:
            app.dependency_overrides.clear()

    def test_default_triggered_by_is_user(self, client):
        session = make_fake_session(killed_ids=[])
        app.dependency_overrides[get_session] = lambda: session
        try:
            resp = client.post("/api/kill-switch", json={})
            assert resp.status_code == 200
            assert resp.json()["triggered_by"] == "user"
        finally:
            app.dependency_overrides.clear()

    def test_returns_valid_uuid_and_timestamps(self, client, two_live_ids):
        session = make_fake_session(killed_ids=two_live_ids)
        app.dependency_overrides[get_session] = lambda: session
        try:
            resp = client.post("/api/kill-switch", json={"reason": "test"})
            data = resp.json()
            uuid.UUID(data["id"])
            datetime.fromisoformat(data["created_at"])
            datetime.fromisoformat(data["updated_at"])
        finally:
            app.dependency_overrides.clear()


class TestKillSwitchStates:
    def test_kill_switch_targets_correct_states(self):
        targets = StrategyStatus.kill_switch_states()
        assert StrategyStatus.LIVE in targets
        assert StrategyStatus.PAPER_TRADING in targets
        assert StrategyStatus.HALTED in targets

    def test_killed_has_no_outgoing_transitions(self):
        from backend.app.models.enums import VALID_TRANSITIONS
        assert VALID_TRANSITIONS[StrategyStatus.KILLED] == frozenset()

    def test_non_killable_states_not_targeted(self):
        targets = StrategyStatus.kill_switch_states()
        assert StrategyStatus.GENERATED not in targets
        assert StrategyStatus.BACKTESTING not in targets
        assert StrategyStatus.RETIRED not in targets
        assert StrategyStatus.KILLED not in targets
