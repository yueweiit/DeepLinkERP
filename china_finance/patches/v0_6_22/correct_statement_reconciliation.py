def execute():
	from china_finance.services.statement_mapping_repair import repair_cash_flow_mappings

	repair_cash_flow_mappings(apply=True)
