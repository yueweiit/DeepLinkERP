app_name = "oa_purchase_request"
app_title = "OA Purchase Request"
app_publisher = "yuewei"
app_description = "OA purchase request DocType for ERPNext"
app_email = "308642281@qq.com"
app_license = "mit"

required_apps = ["erpnext"]

after_install = "oa_purchase_request.install.after_install"
after_migrate = "oa_purchase_request.install.create_or_update_oa_purchase_request"

doctype_js = {
	"OA Purchase Request": "public/js/oa_purchase_request.js",
}

doc_events = {
	"OA Purchase Request": {
		"after_insert": "oa_purchase_request.oa_purchase_request.oa_purchase_request.sync_attachments",
		"on_update": "oa_purchase_request.oa_purchase_request.oa_purchase_request.sync_attachments",
		"before_save": "oa_purchase_request.oa_purchase_request.oa_purchase_request.normalize_child_tables",
	},
	"Purchase Order": {
		"validate": "oa_purchase_request.latingo_backfill.sync_latingo_purchase_order_review_flags",
		"before_submit": "oa_purchase_request.latingo_backfill.validate_latingo_purchase_order_submission",
		"on_submit": "oa_purchase_request.oa_purchase_request.oa_purchase_request.auto_create_purchase_receipt",
	},
}
