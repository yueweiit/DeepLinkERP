from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import nowdate

from mes_integration.mes_integration.integration_log import (
	log_inbound_material_request,
	write_material_request_creation_log,
)
from mes_integration.mes_integration.material_request import (
	build_material_request_task_name,
	build_mes_material_request_name,
	create_and_submit_material_request_payload,
	create_and_submit_material_request_from_mes,
	enqueue_mes_material_request_bin_sync_job,
	recover_material_request_tasks,
	process_material_request_task,
	sync_material_request_bins,
)


class TestMESMaterialRequest(UnitTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_material_request_creation_log_skips_disabled_company(self):
		doc = frappe._dict(
			doctype="Material Request",
			material_request_type="Material Issue",
			company="Disabled Company",
			name="MAT-MR-TEST",
		)

		with (
			patch(
				"mes_integration.mes_integration.integration_log.is_mes_integration_enabled",
				return_value=False,
			),
			patch(
				"mes_integration.mes_integration.integration_log.enqueue_material_request_creation_log"
			) as enqueue_log,
		):
			log_inbound_material_request(doc, "after_insert")

		enqueue_log.assert_not_called()

	def test_material_request_creation_log_requests_background_retry(self):
		with patch(
			"mes_integration.mes_integration.integration_log.create_mes_log",
			side_effect=RuntimeError("temporary database failure"),
		):
			with self.assertRaises(frappe.RetryBackgroundJobError):
				write_material_request_creation_log("MAT-MR-TEST")

	def test_material_request_retries_after_deadlock(self):
		created_doc = frappe._dict(
			name="MAT-MR-MES-RETRY",
			material_request_type="Material Issue",
			docstatus=1,
		)

		with (
			patch(
				"mes_integration.mes_integration.material_request.validate_mes_material_request_permissions"
			),
			patch(
				"mes_integration.mes_integration.material_request.is_mes_integration_enabled",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.material_request.create_material_request_attempt",
				side_effect=[frappe.QueryDeadlockError("deadlock"), created_doc],
			),
			patch("mes_integration.mes_integration.material_request.time.sleep") as sleep,
			patch.object(frappe.db, "rollback") as rollback,
		):
			create_and_submit_material_request_payload(
				{
					"doctype": "Material Request",
					"material_request_type": "Material Issue",
					"company": "Test Company",
					"items": [{"item_code": "TEST-ITEM", "qty": 1}],
				}
			)

		sleep.assert_called_once_with(0.1)
		rollback.assert_called_once_with()
		self.assertEqual(frappe.response["data"]["material_request"], created_doc.name)

	def test_material_request_reuses_existing_mes_request_number(self):
		company = frappe.db.get_value("Company", {"is_group": 0}, "name")
		item = frappe.db.get_value(
			"Item",
			{"is_stock_item": 1, "disabled": 0},
			["name", "stock_uom"],
			as_dict=True,
		)
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0}, "name"
		)

		if not company or not item or not item.stock_uom or not warehouse:
			self.skipTest("需要至少一个公司、库存物料和非组仓库")

		request_number = f"MES-IDEMPOTENCY-{frappe.generate_hash(length=10)}"
		material_request = {
			"doctype": "Material Request",
			"material_request_type": "Material Issue",
			"company": company,
			"custom_material_request_no": request_number,
			"items": [
				{
					"item_code": item.name,
					"qty": 1,
					"uom": item.stock_uom,
					"stock_uom": item.stock_uom,
					"conversion_factor": 1,
					"warehouse": warehouse,
					"schedule_date": nowdate(),
				}
			],
		}

		with (
			patch(
				"mes_integration.mes_integration.material_request.is_mes_integration_enabled",
				return_value=True,
			),
				patch(
					"mes_integration.mes_integration.integration_log.is_mes_integration_enabled",
					return_value=False,
			),
			patch("frappe.enqueue"),
		):
				create_and_submit_material_request_payload(material_request)
				first_response = frappe.response["data"].copy()

				create_and_submit_material_request_payload(material_request)
				second_response = frappe.response["data"]

		self.assertEqual(first_response["material_request"], second_response["material_request"])
		self.assertTrue(second_response["idempotent_reuse"])
		self.assertEqual(
			frappe.db.count(
				"Material Request",
				{"company": company, "custom_material_request_no": request_number},
			),
			1,
		)

	def test_async_material_request_returns_task_without_creating_request(self):
		company = frappe.db.get_value("Company", {"is_group": 0}, "name")
		item = frappe.db.get_value(
			"Item",
			{"is_stock_item": 1, "disabled": 0},
			["name", "stock_uom"],
			as_dict=True,
		)
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0}, "name"
		)

		if not company or not item or not item.stock_uom or not warehouse:
			self.skipTest("需要至少一个公司、库存物料和非组仓库")

		request_number = f"MES-ASYNC-{frappe.generate_hash(length=10)}"
		detail_count = 5000
		material_request = {
			"doctype": "Material Request",
			"material_request_type": "Material Issue",
			"company": company,
			"custom_material_request_no": request_number,
			"items": [
				{
					"item_code": item.name,
					"qty": detail_count,
					"uom": item.stock_uom,
					"stock_uom": item.stock_uom,
					"conversion_factor": 1,
					"warehouse": warehouse,
					"schedule_date": nowdate(),
				}
			],
			"custom_item_details": [
				{
					"material_request_item_idx": 1,
					"item_code": item.name,
					"order_qty": 1,
					"issue_qty": 1,
					"uom": item.stock_uom,
				}
				for _ in range(detail_count)
			],
		}

		with (
			patch(
				"mes_integration.mes_integration.material_request.is_mes_integration_enabled",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.validate_mes_api_user",
			),
			patch(
				"mes_integration.mes_integration.material_request.schedule_material_request_task"
			) as schedule_task,
		):
			create_and_submit_material_request_from_mes(material_request=material_request)
			first_response = frappe.response["data"].copy()
			create_and_submit_material_request_from_mes(material_request=material_request)
			second_response = frappe.response["data"].copy()

		self.assertEqual(first_response["status"], "queued")
		self.assertEqual(first_response["task_status"], "Queued")
		self.assertTrue(first_response["task_id"])
		self.assertEqual(first_response["task_id"], second_response["task_id"])
		self.assertTrue(second_response["idempotent_reuse"])
		self.assertEqual(schedule_task.call_count, 2)
		schedule_task.assert_any_call(first_response["task_id"])
		self.assertFalse(
			frappe.db.exists(
				"Material Request",
				{"company": company, "custom_material_request_no": request_number},
			)
		)
		task = frappe.get_doc("MES Material Request Task", first_response["task_id"])
		self.assertEqual(task.detail_count, detail_count)
		self.assertTrue(task.request_payload)

	def test_material_request_task_worker_updates_success(self):
		task_name = build_material_request_task_name("Test Company", "MES-TASK-TEST")
		task = frappe.get_doc(
			{
				"doctype": "MES Material Request Task",
				"name": task_name,
				"request_key": "MES-TASK-TEST",
				"company": "Test Company",
				"status": "Queued",
				"submitted_by": frappe.session.user,
				"request_payload": frappe.as_json(
					{
						"doctype": "Material Request",
						"material_request_type": "Material Issue",
						"company": "Test Company",
						"items": [{"item_code": "TEST-ITEM", "qty": 1}],
					}
				),
			}
		)
		task.insert(ignore_permissions=True, ignore_links=True, set_name=task_name)

		with (
			patch(
				"mes_integration.mes_integration.material_request.create_and_submit_material_request_payload",
				return_value=frappe._dict(name="MAT-MR-MES-TASK"),
			),
			patch.object(frappe.db, "commit"),
		):
			process_material_request_task(task_name)

		self.assertEqual(
			frappe.db.get_value("MES Material Request Task", task_name, "status"),
			"Success",
		)
		self.assertEqual(
			frappe.db.get_value(
				"MES Material Request Task", task_name, "material_request"
			),
			"MAT-MR-MES-TASK",
		)
		self.assertFalse(
			frappe.db.get_value(
				"MES Material Request Task", task_name, "request_payload"
			)
		)

	def test_failed_material_request_task_reuses_latest_payload(self):
		company = frappe.db.get_value("Company", {"is_group": 0}, "name")
		if not company:
			self.skipTest("需要至少一个公司")

		request_key = f"MES-FAILED-RETRY-{frappe.generate_hash(length=10)}"
		task_name = build_material_request_task_name(company, request_key)
		task = frappe.get_doc(
			{
				"doctype": "MES Material Request Task",
				"name": task_name,
				"request_key": request_key,
				"company": company,
				"status": "Failed",
				"submitted_by": frappe.session.user,
				"request_payload": frappe.as_json(
					{
						"doctype": "Material Request",
						"material_request_type": "Material Issue",
						"company": company,
						"items": [{"item_code": "OLD-ITEM", "qty": 1}],
					}
				),
			}
		)
		task.insert(ignore_permissions=True, ignore_links=True, set_name=task_name)

		new_payload = {
			"doctype": "Material Request",
			"material_request_type": "Material Issue",
			"company": company,
			"items": [{"item_code": "NEW-ITEM", "qty": 2}],
		}

		with (
			patch(
				"mes_integration.mes_integration.material_request.is_mes_integration_enabled",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.material_request.schedule_material_request_task"
			) as schedule_task,
		):
			from mes_integration.mes_integration.material_request import queue_material_request_task

			queue_material_request_task(new_payload | {"request_id": request_key})

		task.reload()
		self.assertEqual(task.status, "Queued")
		self.assertEqual(
			frappe.parse_json(task.request_payload)["items"][0]["item_code"], "NEW-ITEM"
		)
		schedule_task.assert_called_once_with(task_name)

	def test_material_request_names_are_scoped_by_company(self):
		request_key = "MES-REQUEST-COMPANY-SCOPE"
		self.assertEqual(
			build_mes_material_request_name(request_key, "Company A"),
			build_mes_material_request_name(request_key, "Company A"),
		)
		self.assertNotEqual(
			build_mes_material_request_name(request_key, "Company A"),
			build_mes_material_request_name(request_key, "Company B"),
		)

	def test_material_request_task_recovery_requeues_queued_tasks(self):
		company = frappe.db.get_value("Company", {"is_group": 0}, "name")
		if not company:
			self.skipTest("需要至少一个公司")

		request_key = f"MES-RECOVERY-{frappe.generate_hash(length=10)}"
		task_name = build_material_request_task_name(company, request_key)
		task = frappe.get_doc(
			{
				"doctype": "MES Material Request Task",
				"name": task_name,
				"request_key": request_key,
				"company": company,
				"status": "Queued",
				"submitted_by": frappe.session.user,
				"request_payload": "{}",
			}
		)
		task.insert(ignore_permissions=True, ignore_links=True, set_name=task_name)

		with patch(
			"mes_integration.mes_integration.material_request.enqueue_material_request_task_job"
		) as enqueue_task:
			recover_material_request_tasks()

		enqueue_task.assert_called_once_with(task_name)

	def test_mes_material_request_name_does_not_use_series(self):
		request_key = "MES-REQUEST-001"
		self.assertEqual(
			build_mes_material_request_name(request_key),
			build_mes_material_request_name(request_key),
		)
		self.assertTrue(build_mes_material_request_name().startswith("MAT-MR-MES-"))

	def test_material_request_bin_sync_job_is_deduplicated(self):
		with patch("frappe.enqueue") as enqueue:
			enqueue_mes_material_request_bin_sync_job(
				material_request_name="MAT-MR-MES-TEST",
				item_warehouse_pairs=[["TEST-ITEM", "Stores - TC"]],
			)

		enqueue.assert_called_once()
		self.assertEqual(
			enqueue.call_args.args[0],
			"mes_integration.mes_integration.material_request.sync_material_request_bins",
		)
		self.assertTrue(enqueue.call_args.kwargs["deduplicate"])
		self.assertEqual(
			enqueue.call_args.kwargs["job_id"],
			"mes-material-request-bin-sync:MAT-MR-MES-TEST",
		)

	def test_material_request_bin_sync_falls_back_if_queue_is_unavailable(self):
		with (
			patch("frappe.enqueue", side_effect=RuntimeError("redis unavailable")),
			patch(
				"mes_integration.mes_integration.material_request.sync_material_request_bins"
			) as sync_bins,
			patch.object(frappe.db, "commit") as commit,
			patch("frappe.log_error"),
		):
			enqueue_mes_material_request_bin_sync_job(
				material_request_name="MAT-MR-MES-TEST",
				item_warehouse_pairs=[["TEST-ITEM", "Stores - TC"]],
			)

		sync_bins.assert_called_once_with(
			material_request_name="MAT-MR-MES-TEST",
			item_warehouse_pairs=[["TEST-ITEM", "Stores - TC"]],
		)
		commit.assert_called_once_with()

	def test_create_and_submit_material_request_with_large_detail_payload(self):
		company = frappe.db.get_value("Company", {"is_group": 0}, "name")
		item = frappe.db.get_value(
			"Item",
			{"is_stock_item": 1, "disabled": 0},
			["name", "stock_uom"],
			as_dict=True,
		)
		warehouse = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 0}, "name"
		)

		if not company or not item or not item.stock_uom or not warehouse:
			self.skipTest("需要至少一个公司、库存物料和非组仓库")

		detail_count = 5000
		material_request = {
			"doctype": "Material Request",
			"material_request_type": "Material Issue",
			"company": company,
			"items": [
				{
					"item_code": item.name,
					"qty": detail_count,
					"uom": item.stock_uom,
					"stock_uom": item.stock_uom,
					"conversion_factor": 1,
					"warehouse": warehouse,
					"schedule_date": nowdate(),
				}
			],
			"custom_item_details": [
				{
					"material_request_item_idx": 1,
					"item_code": item.name,
					"order_qty": 1,
					"issue_qty": 1,
					"uom": item.stock_uom,
				}
				for _ in range(detail_count)
			],
		}

		with (
			patch(
				"mes_integration.mes_integration.material_request.is_mes_integration_enabled",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.validate_mes_api_user",
			),
			patch(
				"mes_integration.mes_integration.integration_log.is_mes_integration_enabled",
				return_value=False,
			),
			patch("frappe.enqueue"),
		):
			create_and_submit_material_request_payload(material_request)

		response_data = frappe.response.get("data") or {}
		self.assertEqual(response_data.get("status"), "success")
		self.assertEqual(response_data.get("material_request_docstatus"), 1)

		material_request_name = response_data["material_request"]
		self.assertEqual(
			frappe.db.count(
				"MES Material Request Item Detail",
				{"parent": material_request_name},
			),
			detail_count,
		)
		self.assertEqual(
			frappe.db.get_value(
				"MES Material Request Item Detail",
				{"parent": material_request_name},
				["docstatus", "material_request_item"],
			),
			(1, frappe.db.get_value("Material Request Item", {"parent": material_request_name}, "name")),
		)

		sync_material_request_bins(
			material_request_name,
			item_warehouse_pairs=[[item.name, warehouse]],
		)
		sync_material_request_bins(
			material_request_name,
			item_warehouse_pairs=[[item.name, warehouse]],
		)

		from erpnext.stock.stock_balance import get_indented_qty

		self.assertAlmostEqual(
			frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": warehouse}, "indented_qty"),
			get_indented_qty(item.name, warehouse),
		)
