"""Bench command for the one-time international-logistics Company provisioning."""

from overseas_costing.services.company_route_provision_service import provision_company_routes


def execute(dry_run=1):
    return provision_company_routes(dry_run=str(dry_run).strip().lower() not in {"0", "false", "no"})
