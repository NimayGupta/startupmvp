"""Unit tests for workers/tasks/feature_refresh.py"""

from unittest.mock import MagicMock, patch

import pytest

from workers.tasks.feature_refresh import (
    _get_active_merchant_ids,
    _write_refresh_events,
)


# ---------------------------------------------------------------------------
# _get_active_merchant_ids
# ---------------------------------------------------------------------------


def test_get_active_merchant_ids_returns_ids():
    fake_rows = [{"id": 1}, {"id": 2}, {"id": 3}]

    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = fake_rows

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    with patch("workers.tasks.feature_refresh.get_sync_db_connection", return_value=mock_conn):
        ids = _get_active_merchant_ids()

    assert ids == [1, 2, 3]


def test_get_active_merchant_ids_empty():
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    with patch("workers.tasks.feature_refresh.get_sync_db_connection", return_value=mock_conn):
        ids = _get_active_merchant_ids()

    assert ids == []


# ---------------------------------------------------------------------------
# _write_refresh_events
# ---------------------------------------------------------------------------


def test_write_refresh_events_inserts_one_row_per_merchant():
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    results = {"total": 3, "success": 3, "failed": 0, "failed_ids": []}

    with patch("workers.tasks.feature_refresh.get_sync_db_connection", return_value=mock_conn):
        _write_refresh_events([1, 2, 3], results)

    # execute should have been called once per merchant
    assert mock_cur.execute.call_count == 3
    mock_conn.commit.assert_called_once()


def test_write_refresh_events_no_merchants_is_noop():
    with patch("workers.tasks.feature_refresh.get_sync_db_connection") as mock_ctx:
        _write_refresh_events([], {"total": 0, "success": 0, "failed": 0, "failed_ids": []})
    mock_ctx.assert_not_called()


# ---------------------------------------------------------------------------
# refresh_all_merchants task (integration-level, mocked HTTP + DB)
# ---------------------------------------------------------------------------


def test_refresh_all_merchants_raises_on_partial_failure():
    """Task raises RuntimeError when any merchant refresh fails."""
    import httpx
    from workers.tasks.feature_refresh import refresh_all_merchants

    mock_response_ok = MagicMock()
    mock_response_ok.raise_for_status = MagicMock()

    def side_effect(url, **kwargs):
        if "merchant_id=2" in url or "/features/2" in url:
            raise httpx.RequestError("timeout")
        return mock_response_ok

    with (
        patch(
            "workers.tasks.feature_refresh._get_active_merchant_ids",
            return_value=[1, 2, 3],
        ),
        patch(
            "workers.tasks.feature_refresh._write_refresh_events",
        ),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = lambda url, **kw: (
            (_ for _ in ()).throw(httpx.RequestError("timeout"))
            if "/features/2" in url
            else mock_response_ok
        )
        mock_client_cls.return_value = mock_client

        # Task should raise so Celery marks it as failed and retries
        with pytest.raises(RuntimeError, match="1 failure"):
            refresh_all_merchants.run()
