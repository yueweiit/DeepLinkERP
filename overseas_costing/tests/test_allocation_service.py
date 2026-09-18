"""中文用途：AI 基础分摊填入服务测试。"""

import json
from unittest.mock import mock_open

from overseas_costing.services import allocation_service


def test_ai_allocation_suggestion_keeps_candidate_amount_and_transport_recommendation(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "summary": "海运费按体积更合理。",
                "rules": [
                    {
                        "rule_code": "china_ocean_usd",
                        "allocation_basis": "volume",
                        "reason": "海运柜货有体积数据，按空间占用分摊。",
                        "confidence": 0.82,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 20, "volume_m3": 3, "transport_mode": "SEA"},
            {"row_no": 2, "goods_value": 200, "gross_weight_kg": 10, "volume_m3": 7, "transport_mode": "SEA"},
        ],
        candidate_rules=[
            {
                "rule_code": "china_ocean_usd",
                "expense_category": "中国海运费",
                "allocation_basis": "gross_weight",
                "currency": "USD",
                "amount": 500,
                "is_enabled": 1,
            }
        ],
        context={"batch_name": "BATCH-001"},
    )

    assert result["ok"] is True
    assert result["source"] == "ai"
    assert result["rules"][0]["amount"] == 500
    assert result["rules"][0]["currency"] == "USD"
    assert result["rules"][0]["allocation_basis"] == "volume"
    assert result["rules"][0]["is_ai_suggestion"] == 1
    assert "AI基础分摊填入" in result["rules"][0]["remark"]
    assert "空间占用" in result["rules"][0]["remark"]


def test_ai_allocation_suggestion_skips_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {"api_key": "", "base_url": "https://example.test/v1", "model": "test-model", "timeout": 3},
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[],
        candidate_rules=[{"rule_code": "fee", "amount": 10, "currency": "RMB"}],
        context={},
    )

    assert result["ok"] is False
    assert result["action"] == "skipped"
    assert "未配置 AI 接口密钥" in result["reason"]


def test_ai_is_constrained_to_server_supplied_available_bases(monkeypatch) -> None:
    captured_messages = []
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )

    def fake_call(_config, messages):
        captured_messages.extend(messages)
        return json.dumps({
            "rules": [{
                "rule_code": "freight",
                "allocation_basis": "volume",
                "reason": "错误地选择不可用体积",
                "confidence": 0.9,
            }],
        }, ensure_ascii=False)

    monkeypatch.setattr(allocation_service, "_call_chat_completions", fake_call)
    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[{"row_no": 1, "goods_value": 100, "gross_weight_kg": 10}],
        candidate_rules=[{
            "rule_code": "freight",
            "amount": 100,
            "currency": "RMB",
            "allocation_basis": "goods_value",
            "available_bases": ["goods_value", "gross_weight"],
        }],
        context={},
    )

    prompt = json.loads(captured_messages[1]["content"])
    assert prompt["data"]["candidate_rules"][0]["available_bases"] == ["goods_value", "gross_weight"]
    assert "available_bases" in captured_messages[0]["content"]
    assert result["rules"][0]["allocation_basis"] == "goods_value"
    assert result["rules"][0]["is_ai_suggestion"] == 0


def test_decision_request_prompt_omits_existing_basis_and_internal_marker(monkeypatch) -> None:
    captured_messages = []
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )

    def fake_call(_config, messages):
        captured_messages.extend(messages)
        return json.dumps({
            "rules": [{
                "rule_code": "freight",
                "allocation_basis": "gross_weight",
                "reason": "重新判断",
                "confidence": 0.8,
            }],
        }, ensure_ascii=False)

    monkeypatch.setattr(allocation_service, "_call_chat_completions", fake_call)
    allocation_service.suggest_allocation_rules_with_ai(
        items=[{"row_no": 1, "goods_value": 100, "gross_weight_kg": 10}],
        candidate_rules=[{
            "rule_code": "freight",
            "amount": 100,
            "currency": "RMB",
            "available_bases": ["goods_value", "gross_weight"],
            "_decision_request": True,
        }],
        context={},
    )

    candidate = json.loads(captured_messages[1]["content"])["data"]["candidate_rules"][0]
    assert "_decision_request" not in candidate
    assert "allocation_basis" not in candidate
    assert "basis_field" not in candidate


def test_ai_config_uses_deepseek_defaults_when_key_exists(monkeypatch) -> None:
    monkeypatch.setattr(allocation_service, "_conf_value", lambda _key: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("OVERSEAS_COST_AI_API_KEY", raising=False)
    monkeypatch.delenv("OVERSEAS_COST_AI_BASE_URL", raising=False)
    monkeypatch.delenv("OVERSEAS_COST_AI_MODEL", raising=False)

    config = allocation_service._ai_config()

    assert config["api_key"] == "test-key"
    assert config["base_url"] == "https://api.deepseek.com"
    assert config["model"] == "deepseek-v4-flash"


def test_ai_payload_and_rule_remark_expose_missing_basis_data(monkeypatch) -> None:
    captured_messages = []
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )

    def fake_call(_config, messages):
        captured_messages.extend(messages)
        return json.dumps(
            {
                "rules": [
                    {
                        "rule_code": "service_fee",
                        "allocation_basis": "gross_weight",
                        "reason": "服务费按重量分摊，毛重数据完整。",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(allocation_service, "_call_chat_completions", fake_call)
    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 20},
            {"row_no": 2, "goods_value": 100, "gross_weight_kg": 0},
        ],
        candidate_rules=[{"rule_code": "service_fee", "amount": 100, "currency": "RMB"}],
        context={},
    )

    prompt_payload = json.loads(captured_messages[1]["content"])["data"]
    assert prompt_payload["totals"]["missing_gross_weight_count"] == 1
    assert result["rules"][0]["basis_missing_count"] == 1
    assert "1 行缺少重量" in result["rules"][0]["remark"]
    assert "毛重数据完整" not in result["rules"][0]["remark"]


def test_ai_payload_uses_effective_shipment_value_instead_of_stale_goods_mirror():
    item = {
        "row_no": 1,
        "goods_value": 0,
        "actual_shipped_qty": 1,
        "shipped_uom": "个",
        "project_collection": "项目-A",
        "supplier": "供应商-A",
        "extra_json": json.dumps({
            "shipment_valuation": {
                "amount_rmb": "500",
                "currency": "RMB",
                "quantity": "1",
                "uom": "个",
                "status": "automatic",
                "error": "",
            }
        }),
    }

    payload = allocation_service._build_ai_prompt_payload(
        items=[item],
        candidate_rules=[{"rule_code": "insurance", "amount": 10, "currency": "RMB"}],
        context={},
    )

    assert payload["items"][0]["goods_value"] == 500
    assert payload["totals"]["total_goods_value"] == 500
    assert payload["totals"]["missing_goods_value_count"] == 0
    assert payload["context"]["project"] == "项目-A"
    assert payload["context"]["supplier"] == "供应商-A"


def test_ai_allocation_supports_chargeable_weight_when_gross_weight_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "rules": [
                    {
                        "rule_code": "china_to_mexico_freight_rmb",
                        "allocation_basis": "chargeable_weight",
                        "reason": "运输费按计费重分摊，重货和抛货取较大值。",
                        "confidence": 0.88,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 0, "volume_weight_kg": 35},
            {"row_no": 2, "goods_value": 100, "gross_weight_kg": 0, "volume_weight_kg": 20},
        ],
        candidate_rules=[{"rule_code": "china_to_mexico_freight_rmb", "amount": 100, "currency": "RMB"}],
        context={},
    )

    assert result["ok"] is True
    assert result["rules"][0]["allocation_basis"] == "chargeable_weight"
    assert "缺少计费重" not in result["rules"][0]["remark"]


def test_ai_transport_basis_is_not_overridden_by_a_hardcoded_default(monkeypatch) -> None:
    monkeypatch.setattr(
        allocation_service,
        "_ai_config",
        lambda: {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "test-model",
            "timeout": 3,
        },
    )
    monkeypatch.setattr(
        allocation_service,
        "_call_chat_completions",
        lambda _config, _messages: json.dumps(
            {
                "rules": [
                    {
                        "rule_code": "oa_sea_freight_rmb",
                        "allocation_basis": "gross_weight",
                        "reason": "海运费按毛重分摊。",
                        "confidence": 0.7,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    result = allocation_service.suggest_allocation_rules_with_ai(
        items=[
            {"row_no": 1, "goods_value": 100, "gross_weight_kg": 10, "volume_weight_kg": 35},
            {"row_no": 2, "goods_value": 100, "gross_weight_kg": 20, "volume_weight_kg": 0},
        ],
        candidate_rules=[{"rule_code": "oa_sea_freight_rmb", "amount": 100, "currency": "RMB"}],
        context={},
    )

    assert result["rules"][0]["allocation_basis"] == "gross_weight"
    assert "默认先按毛重" not in result["rules"][0]["remark"]


def test_conf_value_reads_site_config_when_frappe_conf_is_stale(monkeypatch) -> None:
    class FakeFrappe:
        conf = {}

        @staticmethod
        def get_site_path(*parts):
            return "/fake-site/" + "/".join(parts)

    monkeypatch.setattr(allocation_service, "frappe", FakeFrappe)
    monkeypatch.setattr("builtins.open", mock_open(read_data='{"overseas_cost_ai_api_key":"file-key"}'))

    assert allocation_service._conf_value("overseas_cost_ai_api_key") == "file-key"
