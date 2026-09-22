from overseas_costing.services import company_route_provision_service as service
from overseas_costing.services.company_route_provision_service import (
    EXISTING_COMPANY_ROUTES,
    MEXICO_COMPANIES,
    build_provision_plan,
)


def _existing_core_companies():
    return [{"name": company} for company in EXISTING_COMPANY_ROUTES.values()]


def _mexico_company(name, abbr):
    return {"name": name, "abbr": abbr, "country": "Mexico", "default_currency": "MXN", "is_group": 0, "parent_company": ""}


def test_preflight_lists_six_companies_and_ten_routes_without_writes() -> None:
    plan = build_provision_plan(_existing_core_companies(), [])

    assert plan["ok"] is True
    assert len(plan["create_companies"]) == 6
    assert len(plan["create_routes"]) == 10


def test_preflight_repeated_run_skips_everything() -> None:
    companies = _existing_core_companies() + [_mexico_company(name, abbr) for name, abbr in MEXICO_COMPANIES]
    routes = [
        {"project_collection": project, "subsidiary_code": company, "erp_site": "", "enabled": 1}
        for project, company in {**EXISTING_COMPANY_ROUTES, **{name: name for name, _ in MEXICO_COMPANIES}}.items()
    ]

    plan = build_provision_plan(companies, routes)

    assert plan["ok"] is True
    assert plan["create_companies"] == []
    assert plan["create_routes"] == []
    assert len(plan["skip_routes"]) == 10


def test_preflight_company_conflict_blocks_entire_plan() -> None:
    companies = _existing_core_companies() + [
        {"name": "OTHER", "abbr": "LEMO"},
        _mexico_company("YW MOLDES MX模具", "WRONG"),
    ]

    plan = build_provision_plan(companies, [])

    assert plan["ok"] is False
    assert {row["type"] for row in plan["conflicts"]} == {"COMPANY_FIELD_CONFLICT", "COMPANY_ABBR_CONFLICT"}


def test_preflight_never_maps_lemos_to_shenzhen_company() -> None:
    plan = build_provision_plan(_existing_core_companies(), [])
    route = next(row for row in plan["create_routes"] if row["project_collection"] == "LEMOS MX供应链开发及管理")

    assert route["subsidiary_code"] == "LEMOS MX供应链开发及管理"
    assert "深圳柠檬树" not in route["subsidiary_code"]


class _DB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Doc:
    def __init__(self, fake, values):
        self.fake = fake
        self.values = values

    def insert(self, ignore_permissions=True):
        self.fake.writes.append(dict(self.values))
        if self.values["doctype"] == "Company":
            self.fake.companies.append({"name": self.values["company_name"], **self.values})
        else:
            self.fake.routes.append(dict(self.values))
        return self


class _Frappe:
    def __init__(self, companies):
        self.companies = list(companies)
        self.routes = []
        self.writes = []
        self.db = _DB()

    def only_for(self, role):
        assert role == "System Manager"

    def get_all(self, doctype, **kwargs):
        return list(self.companies if doctype == "Company" else self.routes)

    def get_doc(self, values):
        return _Doc(self, values)


def test_management_command_applies_once_then_is_idempotent(monkeypatch) -> None:
    fake = _Frappe(_existing_core_companies())
    monkeypatch.setattr(service, "frappe", fake)

    first = service.provision_company_routes(dry_run=False)
    second = service.provision_company_routes(dry_run=False)

    assert first["applied"] is True
    assert len(fake.writes) == 16
    assert second["create_companies"] == []
    assert second["create_routes"] == []
    assert fake.db.commits == 2


def test_management_command_conflict_performs_zero_writes(monkeypatch) -> None:
    fake = _Frappe(_existing_core_companies() + [{"name": "OTHER", "abbr": "MOLD"}])
    monkeypatch.setattr(service, "frappe", fake)

    result = service.provision_company_routes(dry_run=False)

    assert result["ok"] is False
    assert result["applied"] is False
    assert fake.writes == []
    assert fake.db.commits == 0
