"""Rename six operating companies and all active ERP references."""

from __future__ import annotations

from overseas_costing.services.company_rename_service import (
    rename_operating_companies as rename_companies,
)


def execute() -> dict:
    return rename_companies()
