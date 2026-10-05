"""Serve synthetic requests through the actual reviewed cashier export adapter.

Run with the cashier project's virtualenv, a disposable directory, and its reviewed
worktree on PYTHONPATH. This fixture never reads a real cashier database.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--data-dir", required=True)
	parser.add_argument("--port", type=int, default=64244)
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
	from backend.app import db
	from backend.app.erp_export import router
	from fastapi import FastAPI
	import uvicorn

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
		db.refresh_payment_summaries(conn, bump_version=False)
	app = FastAPI()
	app.include_router(router)
	print(json.dumps({"qa_source": "http://127.0.0.1:64244", "requests": 130, "payments": 3}))
	uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
	main()
