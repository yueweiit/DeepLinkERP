"""Serve synthetic requests through the actual reviewed cashier export adapter.

Run with the cashier project's virtualenv, a disposable directory, and its reviewed
worktree on PYTHONPATH. This fixture never reads a real cashier database.
"""

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace


OA_CORP = "qa-corp"
OA_PROCESS = "PROC-0DC5DE17-A29A-497C-8A1F-1324298A04AA"
OA_SHEET = "悦为智能 YW Tech_Ai"
OA_LEGAL_COMPANY = "悦为智能技术（东莞）有限公司"


def oa_manifest():
	"""Synthetic original PG rows shared by source preflight and ERP cache seed."""
	rows, tasks = [], []
	for index, case in enumerate(("completed", "cashier", "supervisor", "no-history"), 1):
		instance = "qa-oa-" + case
		completed = case in {"completed", "no-history"}
		created = datetime(2026, 10, 1, tzinfo=timezone.utc)
		forms = [{"name": key, "value": value} for key, value in (
			("申请类型", "付款申请"), ("执行地区", "中国"), ("金额", str(400 + index * 100)),
			("币种", "人民币"), ("事项说明", "QA OA " + case + "（纯合成，无真实付款）"),
			("收款人", "QA Operating Supplier"), ("付款公司", OA_LEGAL_COMPANY))]
		operations, raw_tasks = [], []
		nodes = (("manager", "主管审批"),) if case == "supervisor" else (
			("manager", "主管审批"), ("finance", "财务审批"), ("cashier", "出纳执行"))
		for order, (node, label) in enumerate(nodes, 1):
			done = completed or (case == "cashier" and node != "cashier")
			start = created.replace(hour=order)
			end = start.replace(minute=30) if done else None
			task = {"taskId": instance + "-" + node, "activityId": node, "taskGroupName": label,
				"userId": "qa-" + node, "status": "COMPLETED" if done else "RUNNING",
				"result": "AGREE" if done else "NONE", "createTime": start.isoformat(),
				"pcUrl": "https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?procInstId=" + instance}
			if done:
				task["finishTime"] = end.isoformat()
				operations.append({"activityId": node, "showName": label, "userId": "qa-" + node,
					"type": "EXECUTE_TASK_NORMAL", "result": "AGREE", "date": end.isoformat(), "remark": "QA合成审批同意"})
			raw_tasks.append(task)
			tasks.append({"corp_id": OA_CORP, "process_instance_id": instance, "task_id": task["taskId"],
				"activity_id": node, "node_name": label, "status": task["status"], "result": task["result"],
				"approver_user_id": "qa-" + node, "approver_user_name": label, "start_time": start,
				"end_time": end, "raw_payload": task, "updated_at": created.replace(hour=5)})
		rows.append({"id": index, "corp_id": OA_CORP, "process_instance_id": instance,
			"business_id": "QA-OA-2026-" + str(index), "process_code": OA_PROCESS,
			"status": "COMPLETED" if completed else "RUNNING", "result": "agree" if completed else "NONE",
			"originator_user_id": "qa-stale-creator", "originator_user_name": "QA旧创建人",
			"create_time": created, "updated_at": created.replace(hour=5), "deleted_at": None,
			"form_component_values": forms, "business_count": 1,
			"raw_payload": {"corpId": OA_CORP, "processInstanceId": instance, "originatorUserId": "qa-originator",
				"createTime": created.isoformat(), "businessId": "QA-OA-2026-" + str(index),
				"processVersion": "qa-template-v1", "tasks": raw_tasks, "operationRecords": operations}})
	return {"instances": rows, "tasks": tasks, "users": [
		{"user_id": user, "name": name} for user, name in (("qa-originator", "QA合成申请人"),
			("qa-manager", "QA主管"), ("qa-finance", "QA财务"), ("qa-cashier", "QA出纳"))]}


class SyntheticPG:
	"""Only synthetic rows at the PG boundary; real adapter SQL/parser/policy run."""
	def __init__(self):
		self.manifest = oa_manifest()
		self.rows = []

	def __enter__(self): return self
	def __exit__(self, *args): pass
	def cursor(self): return self
	def _connection(self): return self
	def fetchall(self): return copy.deepcopy(self.rows)

	def execute(self, sql, params=None):
		params = params or ()
		if sql.startswith("SET TRANSACTION") or "attachment_archives_v1" in sql:
			self.rows = []
		elif "public.approval_expense_operation" in sql:
			record_ids = {str(value) for value in params[0]}
			self.rows = [{"source_id": str(10000 + row["id"]), "approval_no": row["business_id"],
				"source_updated_at": row["updated_at"], "raw_identity": {
					"processInstanceId": row["process_instance_id"], "corpId": row["corp_id"],
					"processCode": row["process_code"], "businessId": row["business_id"]}}
				for row in self.manifest["instances"] if str(10000 + row["id"]) in record_ids]
		elif "public.ding_approval_instance" in sql:
			if len(params) == 1:
				# Global identity corroboration is deliberately not corp/scope filtered.
				self.rows = [{**r, "raw_identity": {"corpId": r["corp_id"],
					"processInstanceId": r["process_instance_id"], "processCode": r["process_code"],
					"businessId": r["business_id"]}} for r in self.manifest["instances"]
					if r["process_instance_id"] in params[0]]
			else:
				corp, identities, codes = params
				self.rows = [r for r in self.manifest["instances"] if r["corp_id"] == corp
					and r["process_instance_id"] in identities and r["process_code"] in codes]
		elif "public.ding_approval_task" in sql:
			corp, identities = params
			self.rows = [r for r in self.manifest["tasks"] if r["corp_id"] == corp and r["process_instance_id"] in identities]
		elif "public.ding_user_snapshot" in sql:
			corp, identities = params
			self.rows = [r for r in self.manifest["users"] if corp == OA_CORP and r["user_id"] in identities]
		elif "costing_read.approval_instances_v2" in sql:
			codes, start, end, until = params[:4]
			self.rows = [r for r in self.manifest["instances"] if r["process_code"] in codes
				and start <= r["create_time"] < end and r["updated_at"] <= until]
			if "corp_id=%s AND process_instance_id=%s" in sql:
				corp, instance = params[-3:-1]
				self.rows = [r for r in self.rows if (r["corp_id"], r["process_instance_id"]) == (corp, instance)]
			self.rows.sort(key=lambda row: (row["corp_id"], row["process_instance_id"]))
			self.rows = self.rows[:params[-1]]
		else:
			raise RuntimeError("Unexpected query at synthetic PG boundary")
		return self


def install_oa_source_boundary():
	os.environ["PAYMENT_ERP_EXPORT_ALLOWED_SHEETS"] = json.dumps(["QA运营", OA_SHEET], ensure_ascii=False)
	os.environ["PAYMENT_ERP_OPERATING_OA_SCOPE"] = json.dumps({"corp_id": OA_CORP, "process_code": OA_PROCESS,
		"year": 2026, "execution_region": "中国", "source_sheet": OA_SHEET}, ensure_ascii=False)
	os.environ["PAYMENT_ERP_OPERATING_PAYMENT_POLICY"] = json.dumps({"corp_id": OA_CORP,
		"process_code": OA_PROCESS, "template_version": "qa-template-v1", "policy_version": "qa-policy-v1",
		"required_approval_activity_ids": ["manager", "finance"], "cashier_activity_ids": ["cashier"]})
	os.environ["PAYMENT_ERP_OPERATING_EMPLOYEE_MAPPING_CORP_ID"] = OA_CORP
	from backend.app import external_expenses
	# Replace only connection/config boundaries; never read a credential file or
	# replace the source reader, parser, router or payment eligibility decision.
	external_expenses.source_connection = lambda dbname=None: SyntheticPG()
	external_expenses.source_database_config = lambda: SimpleNamespace(user_dbname="qa-fake-pg")


def seed_oa_cashier_rows(conn, stamp):
	conn.execute("INSERT INTO employee_department_mappings(user_id,employee_name,second_level_department,imported_at) VALUES(?,?,?,?)",
		("qa-originator", "QA合成申请人", OA_SHEET, stamp))
	for index, row in enumerate(oa_manifest()["instances"][:3], 1):
		amount = 400 + index * 100
		external = {"system": "dingtalk_expense_database", "source_type": "operation", "record_id": str(10000 + index),
			"corp_id": OA_CORP, "process_instance_id": row["process_instance_id"], "approval_no": row["business_id"],
			"application_date": "2026-10-01", "application_type_raw": "付款申请", "source_company_raw": OA_LEGAL_COMPANY,
			"applicant_id": "qa-originator", "applicant": "QA合成申请人", "approval_status": row["status"], "approval_result": row["result"]}
		conn.execute("""INSERT INTO payment_requests(id,logical_request_id,batch_id,source_sheet,applicant,payee_name,summary,amount,currency,
			raw_extra_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (2100 + index, 2100 + index, 1001,
			OA_SHEET, "QA合成申请人", "QA Operating Supplier", row["form_component_values"][4]["value"], amount, "CNY",
			json.dumps({"external_source": external}, ensure_ascii=False), stamp, stamp))
		conn.execute("""INSERT INTO payment_records(id,request_id,root_payment_id,amount,payer,remark,source_type,payment_date,created_at,updated_at)
			VALUES(?,?,?,?,?,?,?,?,?,?)""", (3100 + index, 2100 + index, 3100 + index, 10, "QA出纳", "QA合成历史，不是真实付款",
			"manual", "2026-10-02", stamp, stamp))


def check_oa_adapter(app):
	"""Acceptance preflight: real HTTP adapter, parser and policy, never canned decisions."""
	from backend.app.erp_export import digest
	from fastapi.testclient import TestClient
	from unittest.mock import patch
	identities = [{"corp_id": "qa-corp", "process_instance_id": "qa-oa-" + case,
		"source_id": "oa:" + digest(["qa-corp", "qa-oa-" + case])}
		for case in ("completed", "cashier", "supervisor", "no-history")]
	with TestClient(app) as client:
		response = client.post("/api/integrations/erp/operating-expenses/workflow",
			headers={"Authorization": "Bearer operating-source-qa-only"}, json={"identities": identities})
		assert response.status_code == 200, "Synthetic schema2 workflow unavailable: " + response.text
		payload = response.json()
		assert payload["schema_version"] == 2 and len(payload["items"]) == 4
		for identity, item, allowed in zip(identities, payload["items"], (True, True, False, True)):
			assert item["source_id"] == identity["source_id"] and item["lookup_status"] == "found"
			assert item["originator"] == {"id": "qa-originator", "name": "QA合成申请人"}
			assert item["payment_eligibility"]["can_register_payment"] is allowed
		assert payload["items"][0]["approval_status"] == "COMPLETED"
		assert payload["items"][0]["current_tasks"] == []
		assert payload["items"][1]["payment_eligibility"]["policy_version"] == "qa-policy-v1"
		assert payload["items"][1]["current_tasks"][0]["stage"] == "出纳执行"
		assert payload["items"][2]["current_tasks"][0]["stage"] == "主管审批"
		with patch.dict(os.environ, {"PAYMENT_ERP_OPERATING_PAYMENT_POLICY": "null"}):
			unconfigured = client.post("/api/integrations/erp/operating-expenses/workflow",
				headers={"Authorization": "Bearer operating-source-qa-only"}, json={"identities": [identities[1]]})
			assert unconfigured.status_code == 200
			assert unconfigured.json()["items"][0]["payment_eligibility"]["can_register_payment"] is False
		wrong = {**identities[1], "corp_id": "qa-other-corp"}
		wrong["source_id"] = "oa:" + digest([wrong["corp_id"], wrong["process_instance_id"]])
		foreign = client.post("/api/integrations/erp/operating-expenses/workflow",
			headers={"Authorization": "Bearer operating-source-qa-only"}, json={"identities": [wrong]})
		assert foreign.status_code == 200 and foreign.json()["items"][0]["lookup_status"] == "missing"
		assert foreign.json()["items"][0]["payment_eligibility"]["can_register_payment"] is False
		resolution = client.post("/api/integrations/erp/resolve-applicant-companies",
			headers={"Authorization": "Bearer operating-source-qa-only"},
			json={"applicants": [{"corp_id": OA_CORP, "user_id": "qa-originator", "employee_name": "QA合成申请人"}]})
		assert resolution.status_code == 200 and resolution.json()["schema_version"] == 2
		assert resolution.json()["items"][0]["assigned_department"] == OA_SHEET
		cashier = client.get("/api/integrations/erp/operating-expenses", params={"limit": 500},
			headers={"Authorization": "Bearer operating-source-qa-only"})
		assert cashier.status_code == 200
		evidence = {item.get("process_instance_id"): item for item in cashier.json()["items"] if item.get("corp_id") == OA_CORP}
		for identity in identities[:3]:
			assert evidence[identity["process_instance_id"]]["paid_amount"] == "10"
		assert identities[3]["process_instance_id"] not in evidence
	print(json.dumps({"qa_oa_adapter_checks": 4, "cases": [i["process_instance_id"] for i in identities]}))


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--data-dir", required=True)
	parser.add_argument("--port", type=int, default=64244)
	parser.add_argument("--check-oa", action="store_true", help="Validate schema2 without binding or restarting port 64244")
	parser.add_argument("--oa-scenarios", action="store_true", help="Include exact-corp synthetic OA schema2 scenarios")
	args = parser.parse_args()
	data = Path(args.data_dir).resolve()
	allowed_parents = {Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve()}
	if data.parent not in allowed_parents or not data.name.startswith("operating-expenses-source-qa."):
		raise RuntimeError("Use a dedicated mktemp QA directory")
	if not data.is_dir() or (data / "app.db").exists():
		raise RuntimeError("Expected a new, empty dedicated QA directory")
	if args.port != 64244:
		raise RuntimeError("QA source uses the dedicated local port 64244")
	os.environ["PAYMENT_APP_DATA_DIR"] = str(data)
	os.environ["PAYMENT_APP_DB"] = str(data / "app.db")
	os.environ["PAYMENT_ATTACHMENT_STORAGE_DIR"] = str(data / "storage")
	os.environ["PAYMENT_ERP_EXPORT_TOKEN"] = "operating-source-qa-only"
	os.environ["PAYMENT_ERP_EXPORT_ALLOWED_SHEETS"] = '["QA运营"]'
	os.environ["PAYMENT_ERP_TAKEOVER_ENABLED"] = "true"
	from backend.app import db
	from backend.app.erp_export import router
	from fastapi import FastAPI
	import uvicorn
	if args.oa_scenarios or args.check_oa:
		install_oa_source_boundary()

	db.init_db()
	# A newly built source must be newer than the ERP's prior incremental
	# watermark. Business dates below remain fixed for repeatable assertions.
	stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
	storage = data / "storage"
	storage.mkdir(exist_ok=True)
	proofs = {
		"qa-application.txt": b"Synthetic QA operating application. No real business data.\n",
		"qa-payment-2001.txt": b"Synthetic QA payment proof 2001 / 20 CNY. Not a real payment.\n",
	}
	for filename, content in proofs.items():
		(storage / filename).write_bytes(content)
	with db.connect() as conn:
		conn.execute("INSERT INTO request_batches(id,name,created_at,updated_at) VALUES(1001,?,?,?)",
			("QA运营费用合成批次", stamp, stamp))
		for index in range(1, 131):
			request_id = 1000 + index
			currency = "MXN" if index == 6 else "CNY"
			company = "QA Operating Mexico" if index == 6 else "QA Operating China"
			type_raw = "费用报销" if index == 2 else "付款申请"
			external = {"system": "dingtalk_expense_database", "source_type": "operation",
				"record_id": f"qa-operating-{index:03}", "application_date": "2026-10-01",
				"application_type_raw": type_raw, "source_company_raw": company,
				"approval_status": "COMPLETED", "approval_result": "refuse" if index == 4 else "agree"}
			if index in (1,8):
				external.update(process_instance_id=f"qa-operating-process-{index}", corp_id="qa-corp",
					workflow_url=f"https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?procInstId=qa-operating-process-{index}")
			if index == 3:
				external.pop("application_type_raw")
			if index == 5:
				external.pop("source_company_raw")
			amount = 0 if index == 7 else index * 100
			conn.execute("""INSERT INTO payment_requests(id,logical_request_id,batch_id,source_sheet,
				applicant,payee_name,summary,amount,currency,raw_extra_json,created_at,updated_at)
				VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (request_id, request_id, 1001, "QA运营",
				"QA员工", "QA员工" if index == 2 else "QA运营供应商",
				f"QA运营费用 {index:03}（纯合成，无真实付款）", amount, currency,
				json.dumps({"external_source": external}, ensure_ascii=False), stamp, stamp))
		for payment_id, request_id, amount in ((2001, 1001, 20), (2002, 1001, 30), (2003, 1002, 200)):
			conn.execute("""INSERT INTO payment_records(id,request_id,root_payment_id,amount,
				payer,remark,source_type,payment_date,created_at,updated_at)
				VALUES(?,?,?,?,?,?,?,?,?,?)""", (payment_id, request_id, payment_id, amount,
				"QA出纳", "合成付款证据，不是实际付款", "manual", "2026-10-02", stamp, stamp))
		conn.execute("""INSERT INTO attachment_links(id,request_id,label,url_path,attachment_type,
			file_path,original_filename,mime_type,file_size,created_at)
			VALUES(3001,1001,?,?,'file',?,?,'text/plain',?,?)""",
			("合成申请附件", "/api/requests/1001/attachments/3001/file", "storage/qa-application.txt",
			"qa-application.txt", len(proofs["qa-application.txt"]), stamp))
		conn.execute("""INSERT INTO payment_vouchers(id,payment_id,label,file_path,
			original_filename,mime_type,file_size,created_at)
			VALUES(4001,2001,?,?,?,'text/plain',?,?)""",
			("合成付款依据", "storage/qa-payment-2001.txt", "qa-payment-2001.txt",
			len(proofs["qa-payment-2001.txt"]), stamp))
		# The production application maintains these states through this same
		# native helper. Run it only while constructing disposable QA records.
		if args.oa_scenarios or args.check_oa:
			seed_oa_cashier_rows(conn, stamp)
		db.refresh_payment_summaries(conn, bump_version=False)
		for request_id in (1001,1008):
			for index,(stage,operator,comment) in enumerate((("提交申请","QA员工","合成申请"),("部门审批","QA经理","合成审批同意"),("财务审批","QA财务","金额与收款方已核对"))):
				conn.execute("""INSERT INTO dingtalk_workflow_events(request_id,event_key,process_instance_id,stage_name,operator_name,event_time,result,comment,is_current,sequence_index,synced_at,created_at,updated_at)
					VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(request_id,f"qa-node-{index}",f"qa-operating-process-{request_id-1000}",stage,operator,f"2026-10-01T0{index+1}:00:00Z","agree",comment,0,index,stamp,stamp,stamp))
	app = FastAPI()
	app.include_router(router)
	if args.oa_scenarios or args.check_oa:
		check_oa_adapter(app)
	if args.check_oa:
		return
	print(json.dumps({"qa_source": "http://127.0.0.1:64244", "requests": 133 if args.oa_scenarios else 130,
		"payments": 6 if args.oa_scenarios else 3, "oa_scenarios": bool(args.oa_scenarios)}))
	uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
	main()
