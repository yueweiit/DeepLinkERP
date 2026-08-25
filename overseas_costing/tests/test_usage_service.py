from __future__ import annotations

from overseas_costing.services import usage_service


def test_get_usage_summary_uses_v16_safe_aggregate_queries(monkeypatch) -> None:
    queries = []

    class FakeDB:
        @staticmethod
        def count(doctype, filters):
            assert doctype == "Overseas Cost Usage Log"
            assert filters == {"creation": [">=", "2026-08-01"]}
            return 3

        @staticmethod
        def sql(query, params, as_dict=False):
            queries.append({"query": query, "params": params, "as_dict": as_dict})
            return []

    class FakeFrappe:
        db = FakeDB()

    monkeypatch.setattr(usage_service, "frappe", FakeFrappe)
    monkeypatch.setattr(usage_service, "nowdate", lambda: "2026-08-31")
    monkeypatch.setattr(usage_service, "add_days", lambda date, days: "2026-08-01")
    monkeypatch.setattr(usage_service, "now_datetime", lambda: "2026-08-31 12:00:00")

    result = usage_service.get_usage_summary(days=30)

    assert result["total"] == 3
    assert len(queries) == 2
    assert all(query["params"] == {"since_date": "2026-08-01"} for query in queries)
    assert all(query["as_dict"] for query in queries)
    assert "COUNT(name) AS action_count" in queries[0]["query"]
    assert "MAX(creation) AS last_seen" in queries[0]["query"]
    assert "GROUP BY operator_name, operator_full_name" in queries[0]["query"]
    assert "GROUP BY action_type" in queries[1]["query"]
