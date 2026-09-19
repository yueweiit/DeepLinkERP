from china_finance.services.voucher import backfill_period_closing_voucher_numbers
from china_finance.setup.install import (
	backfill_source_voucher_numbers,
	sync_period_closing_voucher_number_field,
)


def execute():
	sync_period_closing_voucher_number_field()
	backfill_period_closing_voucher_numbers(apply=True)
	backfill_source_voucher_numbers()
