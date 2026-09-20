def execute():
	from china_finance.services.statement_mapping_repair import repair_cash_flow_mappings
	from china_finance.setup.install import sync_china_financial_statement_report_filters

	sync_china_financial_statement_report_filters()
	repair_cash_flow_mappings(apply=True)
