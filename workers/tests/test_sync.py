"""Unit tests for the bulk sync task helpers."""
from workers.tasks.sync import _extract_gid, _ninety_days_ago_iso


def test_extract_gid_standard() -> None:
    assert _extract_gid("gid://shopify/Product/123456") == "123456"


def test_extract_gid_variant() -> None:
    assert _extract_gid("gid://shopify/ProductVariant/789") == "789"


def test_extract_gid_already_numeric() -> None:
    assert _extract_gid("123") == "123"


def test_extract_gid_empty() -> None:
    assert _extract_gid("") == ""


def test_ninety_days_ago_format() -> None:
    result = _ninety_days_ago_iso()
    # Should be a valid ISO 8601 UTC string ending in Z
    assert result.endswith("Z")
    assert "T" in result
    # Should be parseable
    from datetime import datetime
    dt = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    assert dt is not None


def test_ninety_days_ago_is_past() -> None:
    from datetime import datetime, timezone
    result = _ninety_days_ago_iso()
    dt = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    assert dt < now
