from __future__ import annotations

from overseas_costing.services import usage_service


def test_get_usage_summary_uses_frappe_v16_aggregate_fields(monkeypatch) -> None:
    queries = []

    class FakeDB:
        @staticmethod
        def count(doctype, filters):
            assert doctype == "Overseas Cost Usage Log"
            assert filters == {"creation": [">=", "2026-08-01"]}
            return 3

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_all(doctype, **kwargs):
            assert doctype == "Overseas Cost Usage Log"
            queries.append(kwargs)
            return []

    monkeypatch.setattr(usage_service, "frappe", FakeFrappe)
    monkeypatch.setattr(usage_service, "nowdate", lambda: "2026-08-31")
    monkeypatch.setattr(usage_service, "add_days", lambda date, days: "2026-08-01")
    monkeypatch.setattr(usage_service, "now_datetime", lambda: "2026-08-31 12:00:00")

    result = usage_service.get_usage_summary(days=30)

    assert result["total"] == 3
    assert queries[0]["fields"] == [
        "operator_name",
        "operator_full_name",
        {"COUNT": "name", "as": "action_count"},
        {"MAX": "creation", "as": "last_seen"},
    ]
    assert queries[1]["fields"] == ["action_type", {"COUNT": "name", "as": "action_count"}]
