from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "plm-server" / "src" / "main" / "resources" / "db" / "migration" / "V20260727_1300__ecount_material_groups.sql"
DEFAULT_SOURCE = Path("D:/work/资料/PLM/01 ECOUNT 新物料编码总表.csv")

CONFLICT_MAJOR_CODES = {"MJ", "GL", "SB", "KGFL"}
EXCEPTION_MAJOR_CODES = {"0", "JG", "RC", "WX", "NHA", "NAR", "HE", "WJ"}
SERVICE_MAJOR_CODES = {"JG", "RC", "WX"}

NORMALIZED_MAJOR_DISPLAY = {
    "MJ": "MJ 模具/模架",
    "GL": "GL 金属材料",
    "SB": "SB 设备",
    "KGFL": "KGFL 客供辅料",
}


def text(value: object) -> str:
    return "" if value is None else str(value).replace("\ufeff", "").strip()


def sql_literal(value: object) -> str:
    if value is None:
        return "null"
    return "'" + str(value).replace("'", "''") + "'"


def sql_int(value: int) -> str:
    return str(int(value))


def resolve_default_source() -> Path:
    if DEFAULT_SOURCE.exists():
        return DEFAULT_SOURCE
    matches = sorted(Path("D:/work").glob("*/PLM/01 ECOUNT*.csv"))
    if matches:
        return matches[0]
    return DEFAULT_SOURCE


def read_ecount_rows(csv_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_no, row in enumerate(reader, start=1):
            if row_no < 5:
                continue
            padded = row + [""] * 13
            inventory_code = text(padded[6])
            inventory_name = text(padded[7])
            if not inventory_code or not inventory_name:
                continue
            rows.append(
                {
                    "row_no": str(row_no),
                    "ecount_major_code": text(padded[1]),
                    "ecount_major_name": text(padded[2]),
                    "ecount_minor_code": text(padded[3]),
                    "ecount_minor_name": text(padded[4]),
                }
            )
    return rows


def derive_inventory_type(major_code: str, major_name: str) -> str:
    if major_code in SERVICE_MAJOR_CODES or major_name in {"加工", "日常工作", "费用"}:
        return "unsupported"
    if major_code == "YL":
        return "material"
    if major_code == "GL" and major_name in {"钢料", "铜料"}:
        return "material"
    if major_code in {"FL", "KGFL", "NHA", "NAR", "0"} or major_name == "辅料":
        return "packaging"
    if major_code in {"GJ", "HE", "WJ", "MJ", "KGMJ", "SB", "KGSB"}:
        return "tooling"
    if major_name in {"工具", "模具", "模架", "模芯", "设备", "客供模具"}:
        return "tooling"
    return "unsupported"


def warning_for_major(major_code: str, major_name: str) -> str:
    warnings: list[str] = []
    if major_code in CONFLICT_MAJOR_CODES:
        warnings.append("同一级编码存在多个名称，已保留 ECOUNT 原始编码/名称并使用规范显示名")
    if major_code in SERVICE_MAJOR_CODES or major_name in {"加工", "日常工作", "费用"}:
        warnings.append("非库存/服务/费用类，不建议自动导入 Inventory")
    if major_code in EXCEPTION_MAJOR_CODES - SERVICE_MAJOR_CODES:
        warnings.append("历史小类或异常编码，建议人工复核")
    if major_code == "GL" and major_name == "辅料":
        warnings.append("GL/辅料 与金属材料编码口径冲突")
    if major_code == "SB" and major_name == "工具":
        warnings.append("SB/工具 与设备编码口径冲突")
    if major_code == "0":
        warnings.append("异常一级编码 0，建议放入待清洗队列")
    return "；".join(dict.fromkeys(warnings))


def build_material_groups(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, object]]]:
    major_map: dict[str, dict[str, object]] = {}
    minor_map: dict[str, dict[str, object]] = {}

    for row in rows:
        major_code = text(row.get("ecount_major_code"))
        major_name = text(row.get("ecount_major_name"))
        minor_code = text(row.get("ecount_minor_code"))
        minor_name = text(row.get("ecount_minor_name"))
        if not major_code or not major_name:
            continue

        major_key = f"L1:{major_code}:{major_name}"
        inventory_type = derive_inventory_type(major_code, major_name)
        warning_message = warning_for_major(major_code, major_name)
        major_map.setdefault(
            major_key,
            {
                "group_key": major_key,
                "group_code": major_code,
                "group_name": major_name,
                "group_level": 1,
                "display_name": f"{major_code} {major_name}",
                "normalized_display_name": NORMALIZED_MAJOR_DISPLAY.get(major_code, f"{major_code} {major_name}"),
                "ecount_major_code": major_code,
                "ecount_major_name": major_name,
                "ecount_minor_code": None,
                "ecount_minor_name": None,
                "inventory_type": inventory_type,
                "warning_flag": 1 if warning_message or inventory_type == "unsupported" else 0,
                "warning_message": warning_message,
                "sort_order": 0,
                "record_count": 0,
            },
        )
        major_map[major_key]["record_count"] = int(major_map[major_key]["record_count"]) + 1

        if not minor_code or not minor_name:
            continue
        minor_key = f"L2:{major_code}:{major_name}:{minor_code}:{minor_name}"
        minor_map.setdefault(
            minor_key,
            {
                "group_key": minor_key,
                "parent_group_key": major_key,
                "group_code": minor_code,
                "group_name": minor_name,
                "group_level": 2,
                "display_name": f"{minor_code} {minor_name}",
                "normalized_display_name": f"{minor_code} {minor_name}",
                "ecount_major_code": major_code,
                "ecount_major_name": major_name,
                "ecount_minor_code": minor_code,
                "ecount_minor_name": minor_name,
                "inventory_type": inventory_type,
                "warning_flag": 1 if warning_message or inventory_type == "unsupported" else 0,
                "warning_message": warning_message,
                "sort_order": 0,
                "record_count": 0,
            },
        )
        minor_map[minor_key]["record_count"] = int(minor_map[minor_key]["record_count"]) + 1

    majors = sorted(major_map.values(), key=lambda g: (str(g["group_code"]), str(g["group_name"])))
    minors = sorted(minor_map.values(), key=lambda g: (str(g["ecount_major_code"]), str(g["ecount_major_name"]), str(g["group_code"]), str(g["group_name"])))
    for index, group in enumerate(majors, start=1):
        group["sort_order"] = index * 10
    for index, group in enumerate(minors, start=1):
        group["sort_order"] = index * 10
    return {"majors": majors, "minors": minors}


def value_tuple(group: dict[str, object], parent_column: bool = False) -> str:
    fields = [
        sql_literal(group["group_key"]),
    ]
    if parent_column:
        fields.append(sql_literal(group["parent_group_key"]))
    fields.extend(
        [
            sql_literal(group["group_code"]),
            sql_literal(group["group_name"]),
            sql_int(int(group["group_level"])),
            sql_literal(group["display_name"]),
            sql_literal(group["normalized_display_name"]),
            sql_literal(group["ecount_major_code"]),
            sql_literal(group["ecount_major_name"]),
            sql_literal(group["ecount_minor_code"]),
            sql_literal(group["ecount_minor_name"]),
            sql_literal(group["inventory_type"]),
            sql_int(int(group["warning_flag"])),
            sql_literal(group["warning_message"]),
            sql_int(int(group["record_count"])),
            sql_int(int(group["sort_order"])),
        ]
    )
    return "(" + ", ".join(fields) + ")"


def values_sql(groups: list[dict[str, object]], parent_column: bool = False) -> str:
    return ",\n".join("    " + value_tuple(group, parent_column) for group in groups)


def generate_sql(groups: dict[str, list[dict[str, object]]]) -> str:
    majors = groups["majors"]
    minors = groups["minors"]
    major_values = values_sql(majors)
    minor_values = values_sql(minors, parent_column=True)

    return f"""-- ECOUNT material group dictionary generated from the historical material code master.
-- Seed counts: level1={len(majors)}, level2={len(minors)}

create table if not exists plm_material_group (
    material_group_id bigserial primary key,
    parent_material_group_id bigint references plm_material_group(material_group_id),
    group_key varchar(512) not null,
    group_code varchar(64) not null,
    group_name varchar(255) not null,
    group_level integer not null,
    display_name varchar(512) not null,
    normalized_display_name varchar(512),
    ecount_major_code varchar(64),
    ecount_major_name varchar(255),
    ecount_minor_code varchar(64),
    ecount_minor_name varchar(255),
    inventory_type varchar(64),
    source_system varchar(32) not null default 'ECOUNT',
    source_record_count integer not null default 0,
    warning_flag integer not null default 0,
    warning_message text,
    status varchar(32) not null default 'active',
    sort_order integer not null default 0,
    remark text,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0,
    constraint ck_plm_material_group_level check (group_level in (1, 2)),
    constraint ck_plm_material_group_status check (status in ('draft', 'active', 'inactive', 'archived')),
    constraint ck_plm_material_group_inventory_type check (
        inventory_type is null or inventory_type in ('material', 'semi_finished', 'finished', 'packaging', 'tooling', 'fixture', 'unsupported')
    )
);

create unique index if not exists uk_plm_material_group_active_key
    on plm_material_group(source_system, group_key)
    where deleted_flag = 0;

create index if not exists idx_plm_material_group_parent
    on plm_material_group(parent_material_group_id, sort_order);

create index if not exists idx_plm_material_group_major
    on plm_material_group(ecount_major_code, ecount_major_name);

alter table if exists plm_inventory
    add column if not exists material_group_id bigint;

do $$
begin
    if to_regclass('plm_inventory') is not null
       and not exists (
           select 1 from pg_constraint where conname = 'fk_plm_inventory_material_group'
       ) then
        alter table plm_inventory
            add constraint fk_plm_inventory_material_group
            foreign key (material_group_id) references plm_material_group(material_group_id);
    end if;

    if to_regclass('plm_inventory') is not null then
        create index if not exists idx_plm_inventory_material_group
            on plm_inventory(material_group_id);
    end if;
end $$;

with seed(
    group_key,
    group_code,
    group_name,
    group_level,
    display_name,
    normalized_display_name,
    ecount_major_code,
    ecount_major_name,
    ecount_minor_code,
    ecount_minor_name,
    inventory_type,
    warning_flag,
    warning_message,
    source_record_count,
    sort_order
) as (
values
{major_values}
)
insert into plm_material_group (
    group_key,
    group_code,
    group_name,
    group_level,
    display_name,
    normalized_display_name,
    ecount_major_code,
    ecount_major_name,
    ecount_minor_code,
    ecount_minor_name,
    inventory_type,
    warning_flag,
    warning_message,
    source_record_count,
    sort_order,
    source_system,
    status,
    created_by,
    updated_by,
    deleted_flag
)
select
    seed.group_key,
    seed.group_code,
    seed.group_name,
    seed.group_level,
    seed.display_name,
    seed.normalized_display_name,
    seed.ecount_major_code,
    seed.ecount_major_name,
    seed.ecount_minor_code,
    seed.ecount_minor_name,
    seed.inventory_type,
    seed.warning_flag,
    seed.warning_message,
    seed.source_record_count,
    seed.sort_order,
    'ECOUNT',
    'active',
    'system',
    'system',
    0
from seed
where not exists (
    select 1
    from plm_material_group existing
    where existing.source_system = 'ECOUNT'
      and existing.group_key = seed.group_key
      and existing.deleted_flag = 0
);

with seed(
    group_key,
    parent_group_key,
    group_code,
    group_name,
    group_level,
    display_name,
    normalized_display_name,
    ecount_major_code,
    ecount_major_name,
    ecount_minor_code,
    ecount_minor_name,
    inventory_type,
    warning_flag,
    warning_message,
    source_record_count,
    sort_order
) as (
values
{minor_values}
)
insert into plm_material_group (
    parent_material_group_id,
    group_key,
    group_code,
    group_name,
    group_level,
    display_name,
    normalized_display_name,
    ecount_major_code,
    ecount_major_name,
    ecount_minor_code,
    ecount_minor_name,
    inventory_type,
    warning_flag,
    warning_message,
    source_record_count,
    sort_order,
    source_system,
    status,
    created_by,
    updated_by,
    deleted_flag
)
select
    parent.material_group_id,
    seed.group_key,
    seed.group_code,
    seed.group_name,
    seed.group_level,
    seed.display_name,
    seed.normalized_display_name,
    seed.ecount_major_code,
    seed.ecount_major_name,
    seed.ecount_minor_code,
    seed.ecount_minor_name,
    seed.inventory_type,
    seed.warning_flag,
    seed.warning_message,
    seed.source_record_count,
    seed.sort_order,
    'ECOUNT',
    'active',
    'system',
    'system',
    0
from seed
join plm_material_group parent
  on parent.source_system = 'ECOUNT'
 and parent.group_key = seed.parent_group_key
 and parent.deleted_flag = 0
where not exists (
    select 1
    from plm_material_group existing
    where existing.source_system = 'ECOUNT'
      and existing.group_key = seed.group_key
      and existing.deleted_flag = 0
);

comment on table plm_material_group is 'ECOUNT material group dictionary. It preserves original major/minor group codes and names for historical traceability.';
comment on column plm_material_group.group_key is 'Stable generated key: L1:<major code>:<major name> or L2:<major code>:<major name>:<minor code>:<minor name>.';
comment on column plm_material_group.normalized_display_name is 'Recommended display name for conflicted historical major codes, while original ECOUNT name is preserved.';

do $$
begin
    if to_regclass('plm_inventory') is not null
       and exists (
           select 1
           from information_schema.columns
           where table_name = 'plm_inventory'
             and column_name = 'material_group_id'
       ) then
        comment on column plm_inventory.material_group_id is 'Optional link to ECOUNT material group dictionary.';
    end if;
end $$;
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PLM ECOUNT material group Flyway migration.")
    parser.add_argument("--source", type=Path, default=resolve_default_source(), help="ECOUNT UTF-8 CSV path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Flyway migration output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_ecount_rows(args.source)
    groups = build_material_groups(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generate_sql(groups), encoding="utf-8", newline="\n")
    print(f"source={args.source}")
    print(f"rows={len(rows)}")
    print(f"level1={len(groups['majors'])}")
    print(f"level2={len(groups['minors'])}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
