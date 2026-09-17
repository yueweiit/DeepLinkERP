"""Remove obsolete automatic mappings that target groups or inactive accounts."""

from china_finance.setup.templates import remove_stale_small_enterprise_automatic_mappings


def execute():
	remove_stale_small_enterprise_automatic_mappings()
