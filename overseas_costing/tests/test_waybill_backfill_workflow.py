from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "backfill-comment-waybills.yml"


def test_waybill_backfill_workflow_is_guarded_and_auditable() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "default: audit" in source
    assert '[[ "$WAYBILL_PLAN_HASH" =~ ^[0-9a-f]{64}$ ]]' in source
    assert "backfill_comment_waybills" in source
    assert '\\"dry_run\\": True' in source
    assert '\\"dry_run\\": False' in source
    assert '\\"expected_plan_hash\\": \\"$WAYBILL_PLAN_HASH\\"' in source
    assert "actions/upload-artifact@v4" in source
