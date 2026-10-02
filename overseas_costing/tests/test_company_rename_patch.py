from __future__ import annotations

from pathlib import Path

from overseas_costing.patches.v0_1 import rename_operating_companies as patch


ROOT = Path(__file__).resolve().parents[2]


def test_patch_is_registered_once_and_delegates_to_the_company_rename_service(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        patch,
        "rename_companies",
        lambda: calls.append("rename_companies") or {"ok": True},
    )

    patch.execute()

    entries = [
        line.strip()
        for line in (ROOT / "overseas_costing" / "patches.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert entries.count(
        "overseas_costing.patches.v0_1.rename_operating_companies"
    ) == 1
    assert calls == ["rename_companies"]
