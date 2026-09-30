"""同步库存页面源码与 Frappe 部署副本。"""

from __future__ import annotations

import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PAGE_NAMES = (
    "inventory_location_detail",
    "semi_finished_inventory_detail",
    "finished_goods_inventory_detail",
    "mold_inventory_detail",
)
PUBLIC_ASSETS = (
    "js/categorized_inventory_detail.bundle.js",
    "css/categorized_inventory_detail.bundle.css",
)


def _copy_if_changed(source: Path, target: Path, changed: list[str]) -> None:
    data = source.read_bytes()
    if target.exists() and target.read_bytes() == data:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    changed.append(str(target))


def build_inventory_assets(package_root: str | Path = PACKAGE_ROOT) -> dict[str, list[str]]:
    root = Path(package_root).resolve()
    deployed_root = root / "overseas_costing"
    changed: list[str] = []

    for page_name in PAGE_NAMES:
        source_dir = root / "page" / page_name
        if not source_dir.exists():
            continue
        for source in sorted(path for path in source_dir.iterdir() if path.is_file()):
            _copy_if_changed(
                source,
                deployed_root / "page" / page_name / source.name,
                changed,
            )

    for relative in PUBLIC_ASSETS:
        source = root / "public" / relative
        if source.exists():
            _copy_if_changed(source, deployed_root / "public" / relative, changed)

    return {"changed": changed}


if __name__ == "__main__":
    print(json.dumps(build_inventory_assets(), ensure_ascii=False, indent=2))
