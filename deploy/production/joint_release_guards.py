"""Pure bounded-schema and durable-receipt guards; no database writes here."""

import base64
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

PINNED_INVENTORY_BUNDLES = (
	"public/dist/css-rtl/inventory_detail.bundle.YQO3JEGB.css",
	"public/dist/css/inventory_detail.bundle.TGF3MUFO.css",
	"public/dist/js/inventory_detail.bundle.KYKUWWJK.js",
)


def merge_frozen_branding_sources(base, candidate):
	"""Mirror Docker COPY without accepting arbitrary old source leftovers.

	Legacy AppleDouble files and these six already-compiled inventory assets
	are retained byte-for-byte from the independently verified immutable base.
	They remain in the full audit; none are excluded from source comparisons.
	"""
	dist = {name + suffix for name in PINNED_INVENTORY_BUNDLES for suffix in ("", ".map")}
	appledouble = lambda name: any(part.startswith("._") for part in PurePosixPath(name).parts)
	assert not any(appledouble(name) for name in candidate), "Candidate must not replace/add pinned AppleDouble files"
	present_dist = set(base) & dist
	assert not present_dist or present_dist == dist, "Incomplete pinned inventory bundle/map set"
	for name in present_dist:
		assert name not in candidate or candidate[name] == base[name], "Pinned inventory asset replacement forbidden"
	extra = set(base) - set(candidate)
	assert all(name in dist or appledouble(name) for name in extra), "Tracked source deletion or unknown base-only source"
	return {**{name: base[name] for name in extra}, **candidate}


def serialized(value):
	return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()


def semantic_row(row):
	"""Ignore generated identity/times ONLY when comparing a frozen definition.

	Receipts and rollback always compare complete raw rows, including these fields.
	Behavior flags, NULL/empty defaults, idx, parent links and permissions stay exact.
	"""
	return {key: value for key, value in row.items() if key not in {"name", "creation", "modified", "owner", "modified_by"}}


def assert_schema_delta(before, after, additions):
	assert set(before) == set(after) == {"columns", "indexes", "table"}
	assert set(additions) == {"columns", "indexes"}
	assert before["table"] == after["table"], "Original table options changed"
	for kind in additions:
		assert not set(additions[kind]) & set(before[kind]), "Addition overlaps existing schema"
		for name, definition in before[kind].items():
			assert after[kind].get(name) == definition, f"Original {kind} changed: {name}"
		created = set(after[kind]) - set(before[kind])
		assert created <= set(additions[kind]), f"Unexpected new {kind}"
		for name in created:
			assert after[kind][name] == additions[kind][name], f"Conflicting new {kind}: {name}"


def validate_event_index(rows):
	assert len(rows) == 1, "Event key index must have exactly one column"
	row = rows[0]
	assert row["column"] == "custom_operating_event_key" and row["unique"] == 1
	assert row["prefix"] is None and row.get("type", "BTREE") == "BTREE", "Full-length event key index required"


def validate_identity(identity):
	for key, length in (("candidate_sha", 40), ("contract_sha256", 64)):
		assert isinstance(identity.get(key), str) and re.fullmatch(f"[0-9a-f]{{{length}}}", identity[key])


def assert_pre_resume(path):
	"""Absence alone permits rollback; present/unreadable intent is forward-only."""
	assert Path(path).parent.is_dir() and os.access(Path(path).parent, os.R_OK | os.X_OK), "Resume receipt directory missing/unreadable; maintenance HOLD"
	try:
		os.lstat(path)
	except FileNotFoundError:
		return
	except OSError as error:
		raise AssertionError("Resume marker unreadable; maintenance HOLD, forward-only") from error
	raise AssertionError("First writer resume recorded; maintenance HOLD, forward-only")


def record_resume(path, identity, producer):
	assert re.fullmatch(r"sha256:[0-9a-f]{64}", identity["image_id"])
	contract = {"image_id": identity["image_id"], "first_resume": producer}
	key = {"candidate_sha": identity["candidate_sha"], "contract_sha256": hashlib.sha256(serialized(contract)).hexdigest()}
	if Path(path).exists():
		receipt = DDLReceipt.load(path, key)
		assert receipt.state["contract"] == contract, "Another resume intent; HOLD"
		return receipt.state
	return DDLReceipt.create(path, key, {}, contract).state


def filesystem_budget(operations, *, reserve_bytes=2 * 1024**3):
	"""Actual available bytes, summing concurrent demands on each filesystem."""
	devices = {}
	for kind, (path, amount) in operations.items():
		assert isinstance(amount, int) and amount > 0, "Unknown/invalid space estimate: " + kind
		path = Path(path).resolve(strict=True)
		stats, capacity = os.stat(path), os.statvfs(path)
		available = capacity.f_bavail * capacity.f_frsize
		assert available > 0, "Unknown available filesystem space"
		entry = devices.setdefault(stats.st_dev, {"device": stats.st_dev, "path": str(path), "available_bytes": available, "required_bytes": reserve_bytes, "operations": {}})
		entry["available_bytes"] = min(entry["available_bytes"], available)
		entry["required_bytes"] += amount
		entry["operations"][kind] = amount
	for entry in devices.values():
		assert entry["available_bytes"] >= entry["required_bytes"], "Insufficient filesystem space: " + entry["path"]
	return list(devices.values())


def release_space_budget(archives, image_id, *, main_only=False):
	"""Uncompressed extraction/build/full-with-files backup demands, before any of them."""
	import tarfile
	archives = [Path(value).resolve(strict=True) for value in archives if value]
	expanded = 0
	for path in archives:
		with tarfile.open(path, "r:gz") as archive:
			expanded += sum(member.size for member in archive.getmembers() if member.isfile())
	assert expanded > 0
	if main_only:
		image = json.loads(_host_call(["docker", "image", "inspect", image_id]))[0]
		assert image["Id"] == image_id and image["Size"] > 0 and image["RootFS"]["Layers"], "Unknown real shared image layers; HOLD"
		docker_root = json.loads(_host_call(["docker", "info", "--format", "{{json .DockerRootDir}}"])).strip()
		# COPY overlays share the existing base. Bound the actual copied bytes and
		# layer overhead; post-build verifies the observed image size against this.
		overlay = expanded * 2 + 64 * 1024**2
		operations = {"extraction": ("/tmp", expanded), "candidate_overlay": (docker_root, overlay), "metadata_audit_receipts": (str(Path.cwd()), 256 * 1024**2), "persistent_main_rq": (docker_root, 256 * 1024**2)}
		for index, path in enumerate(archives):
			operations["compressed_archive_" + str(index)] = (path.parent, path.stat().st_size)
		return {"filesystems": filesystem_budget(operations), "expanded_archive_bytes": expanded, "compressed_archive_bytes": sum(path.stat().st_size for path in archives), "base_image_bytes": image["Size"], "overlay_limit_bytes": overlay, "receipt_limit_bytes": 256 * 1024**2, "archives": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in archives}}
	backend = _container_inspect("backend")
	sites = [item for item in backend["Mounts"] if item["Destination"] == "/home/frappe/frappe-bench/sites"]
	assert len(sites) == 1 and sites[0]["Type"] in {"bind", "volume"}, "Unknown backup filesystem; HOLD"
	probe = '''import frappe,json,os
from pathlib import Path
os.chdir("/home/frappe/frappe-bench/sites")
frappe.init(site="deeplinkerp.com",sites_path="/home/frappe/frappe-bench/sites");frappe.connect()
size=frappe.db.sql("SELECT SUM(DATA_LENGTH+INDEX_LENGTH) FROM information_schema.TABLES WHERE TABLE_SCHEMA=database()")[0][0]
attachments=0
for directory in (Path("deeplinkerp.com/public/files"),Path("deeplinkerp.com/private/files")):
 assert directory.is_dir(),"Unknown attachment budget"
 for path in directory.rglob("*"):
  assert not path.is_symlink(),"Unknown shared attachment target"
  if path.is_file():attachments+=path.stat().st_size
print(json.dumps({"database_bytes":int(size),"attachment_bytes":attachments}));frappe.db.rollback();frappe.destroy()
'''
	data = json.loads(_host_call(["docker", "exec", "-e", "FRAPPE_STREAM_LOGGING=1", "frappe_docker-backend-1", "/home/frappe/frappe-bench/env/bin/python", "-c", probe]))
	assert data["database_bytes"] > 0 and data["attachment_bytes"] >= 0
	image = json.loads(_host_call(["docker", "image", "inspect", image_id]))[0]
	assert image["Id"] == image_id and image["Size"] > 0, "Unknown real build demand"
	docker_root = json.loads(_host_call(["docker", "info", "--format", "{{json .DockerRootDir}}"])).strip()
	operations = {"extraction": ("/tmp", expanded * 2),
		"build": (docker_root, image["Size"] * 2 + expanded * 2),
		"full_with_attachments_backup": (sites[0]["Source"], data["database_bytes"] * 12 + data["attachment_bytes"] * 2)}
	return {"filesystems": filesystem_budget(operations), "expanded_archive_bytes": expanded, "base_image_bytes": image["Size"], **data,
		"archives": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in archives}}


JOB_FIELDS = ("origin", "status", "worker_name", "started_at", "ended_at", "last_heartbeat", "timeout", "success_callback_name", "failure_callback_name", "stopped_callback_name", "success_callback_timeout", "failure_callback_timeout", "stopped_callback_timeout", "result_ttl", "failure_ttl", "retries_left", "repeats_left")
SHARED_SITES = ("deeplinkerp.com", "akivision.deeplinkerp.com", "latingo.deeplinkerp.com", "yuewei.deeplinkerp.com")
RELEASE_SERVICES = ("backend", "frontend", "queue-long", "queue-short", "scheduler", "websocket")
NATIVE_RELAY_SOURCES = {
	"frappe/socketio.js": "72bd46b5ae81f718e6dde73d516597e1b7038b70c7339645cc2958a352c71b56",
	"frappe/realtime/index.js": "d9c8a65da1c840c4c92e369625edcec2812523d4f448b5f5a008593c45d0586f",
	"frappe/realtime/handlers.js": "1422a00a66d9367da3683128807899e7abc8c0a3ae9879ead5acd17c3db9d303",
	"frappe/realtime/utils.js": "98a3292c30e2f5803ecd1c06e8756ce9860f5929fe94b96572726deeaa8f81be",
	"frappe/realtime/middlewares/authenticate.js": "a150cbedb44008a24ae697a6173d33493eb8e1bac71887579801a3b522e2c220",
	"frappe/node_utils.js": "c08d86349370fa51b030c93e31b1395caed3813c3a6c68c2e3aff38986b110e2",
	"frappe/frappe/utils/scheduler.py": "f109d9030c3a990a688d2af4b6c510352b2675745f4d1e20b97c041790f124a3",
}


def native_runtime_proof():
	"""Known native relay/scheduler only; site handlers cannot add financial writers."""
	import frappe
	import gunicorn
	import rq
	bench = Path("/home/frappe/frappe-bench")
	assert (frappe.__version__, rq.__version__, gunicorn.__version__) == ("16.23.0", "2.6.1", "23.0.0"), "Unknown native drain version; HOLD"
	for name, expected in NATIVE_RELAY_SOURCES.items():
		assert hashlib.sha256((bench / "apps" / name).read_bytes()).hexdigest() == expected, "Unknown native relay/scheduler source; HOLD: " + name
	assert not any("dedicated_source_sync" in " ".join(value["argv"]) for value in native_processes().values()), "Source child still running; HOLD"
	configs, handlers = {}, {}
	for site in SHARED_SITES:
		frappe.init(site=site, sites_path=str(bench / "sites"))
		frappe.connect()
		try:
			config = frappe.get_site_config(cached=False)
			assert config.get("maintenance_mode") == 1, "Every shared tenant requires approved maintenance; HOLD"
			configs[site] = {"maintenance_mode": 1, "scheduler_disabled": config.get("scheduler_disabled")}
			for app in frappe.get_installed_apps():
				path = bench / "apps" / app / "realtime" / "handlers.js"
				if path.exists():
					assert app == "frappe", "Unreviewed installed realtime handlers: " + site + "/" + app
					handlers[app] = hashlib.sha256(path.read_bytes()).hexdigest()
		finally:
			frappe.db.rollback()
			frappe.destroy()
	return {"native_source_sha256": NATIVE_RELAY_SOURCES, "site_configs": configs, "installed_handlers": handlers}


def verified_quiescence():
	"""A raw isolated drain or this release's durable actual host drain, not an env claim."""
	import frappe
	main_path = os.environ.get("DEEPLINKERP_MAIN_SEAL_RECEIPT")
	if main_path:
		state = DDLReceipt.load(main_path).state
		proof = json.loads(Path(os.environ["DEEPLINKERP_MAIN_SEAL_PROOF"]).read_bytes())
		validate_main_seal(state, proof, os.environ["DEEPLINKERP_RELEASE_CANDIDATE_SHA"])
		assert frappe.local.site == "deeplinkerp.com" and frappe.conf.maintenance_mode == 1, "Main physical maintenance seal required; HOLD"
		assert frappe.conf.db_name == state["contract"]["database"] and frappe.conf.db_user == state["contract"]["new_user"], "Main private authentication seal differs; HOLD"
		assert frappe.db.sql("SELECT CURRENT_USER()")[0][0] == state["contract"]["new_user"] + "@%", "Main command uses another principal; HOLD"
		assert frappe.db.get_single_value("System Settings", "enable_scheduler") in (0, "0", False), "Main global scheduler must remain disabled; HOLD"
		processes = native_processes()
		assert set(processes) == {"1"} and Path(processes["1"]["argv"][0]).name.startswith("python"), "Only the bounded main metadata command may run before resume; HOLD"
		assert_pre_resume(os.environ["DEEPLINKERP_RELEASE_RESUME_RECEIPT"])
		return True
	if getattr(getattr(frappe, "local", None), "site", None) == "operating-release-qa.localhost":
		import redis
		assert frappe.conf.db_host == "db" and frappe.conf.db_name == "_f8a4c563227c1ef2" and frappe.conf.maintenance_mode == 1
		assert os.environ.get("DEEPLINKERP_RELEASE_QUIESCENT") == "1", "Isolated rehearsal quiescence not approved"
		processes = native_processes()
		assert processes["1"]["argv"] == ["sleep", "infinity"], "DDL rehearsal requires its command-only container"
		assert not any(any(word in value["argv"] for word in ("worker", "schedule", "gunicorn", "node")) for value in processes.values()), "Unexpected isolated producer; HOLD"
		config = json.loads(Path("/home/frappe/frappe-bench/sites/common_site_config.json").read_bytes())
		queue = raw_rq_snapshot(redis.Redis.from_url(config["redis_queue"]))
		assert not queue["workers"] and not queue["executions"] and not any(rows for key, rows in queue["registries"].items() if key.startswith("wip:")), "Isolated native workers still active"
		return True
	path = os.environ.get("DEEPLINKERP_RELEASE_DRAIN_RECEIPT")
	if not path:
		return False
	state = DDLReceipt.load(path).state
	assert state["identity"]["candidate_sha"] == os.environ.get("DEEPLINKERP_RELEASE_CANDIDATE_SHA"), "Drain belongs to another candidate; HOLD"
	assert state["status"] == "applied" and set(state["after"]["containers"]) == set(RELEASE_SERVICES), "Actual bounded drain incomplete; HOLD"
	assert all(not value["running"] for value in state["after"]["containers"].values()), "Unconfirmed stopped identity; HOLD"
	assert state["contract"]["one_term_only"] and state["before"].get("native") and state["before"].get("source_host"), "Missing native/source drain proof; HOLD"
	assert_pre_resume(os.environ["DEEPLINKERP_RELEASE_RESUME_RECEIPT"])
	return True


def validate_main_seal(state, proof, candidate_sha):
	"""Require an actual fresh all-Host authentication and namespace observation."""
	assert state["status"] == "applied" and state["identity"]["candidate_sha"] == proof["candidate_sha"] == candidate_sha, "Main seal belongs to another/incomplete release; HOLD"
	assert 0 <= time.time() - proof["observed_at"] <= 120, "Main seal proof is stale; HOLD"
	assert sorted(proof["old_hosts"]) == sorted(state["contract"]["original_hosts"]) and proof["old_accounts_locked"] is True and proof["old_sessions"] == 0, "Main all-Host authentication seal incomplete; HOLD"
	assert sorted(proof["discovered_sites"]) == sorted(SHARED_SITES[1:]), "Main physical namespace seal incomplete; HOLD"
	assert all(proof.get(key) is True for key in ("private_config", "source_idle", "old_containers_unchanged", "producer_containers_stopped")), "Main producer/private credential seal unconfirmed; HOLD"
	assert proof["new_user"] == state["contract"]["new_user"] and proof["database"] == state["contract"]["database"], "Main private DB seal differs; HOLD"


def raw_rq_snapshot(redis, *, main_only=False):
	"""RQ 2.6.1 inventory using raw Redis reads, never native cleanup helpers."""
	def decode(value):
		return value.decode("utf-8", "strict") if isinstance(value, bytes) else value
	keys, cursor = set(), 0
	for _ in range(1000):
		cursor, found = redis.scan(cursor, match="rq:*", count=1000)
		keys.update(decode(key) for key in found)
		assert len(keys) <= 10000, "RQ key inventory exceeds bound; HOLD"
		if cursor == 0:
			break
	else:
		raise AssertionError("Incomplete RQ key inventory; HOLD")

	def typed(key, kind):
		actual = decode(redis.type(key))
		assert actual in {kind, "none"}, "Unexpected Redis key type: " + key
		return actual != "none"
	def members(key):
		if not typed(key, "set"):
			return []
		assert redis.scard(key) <= 50000, "RQ set exceeds bound"
		return sorted(decode(value) for value in redis.smembers(key))
	def listing(key):
		if not typed(key, "list"):
			return []
		assert redis.llen(key) <= 50000, "RQ queue exceeds bound"
		return [decode(value) for value in redis.lrange(key, 0, -1)]
	def registry(key):
		if not typed(key, "zset"):
			return []
		assert redis.zcard(key) <= 50000, "RQ registry exceeds bound"
		return [[decode(value), score] for value, score in redis.zrange(key, 0, -1, withscores=True)]
	def raw_hash(key):
		assert typed(key, "hash"), "Referenced RQ hash missing: " + key
		assert redis.hlen(key) <= 100, "RQ hash exceeds bound"
		assert all(redis.hstrlen(key, field) <= 4096 for field in redis.hkeys(key)), "RQ worker/execution field exceeds bound"
		value = {decode(k): decode(v) for k, v in redis.hgetall(key).items()}
		assert len(serialized(value)) <= 65536, "RQ worker/execution bytes exceed bound"
		return value
	queues = members("rq:queues")
	assert all(key.startswith("rq:queue:") and key.count(":") >= 3 for key in queues), "Unknown RQ queue key"
	result = {"queues": {}, "intermediate": {}, "registries": {}, "workers": {}, "tombstones": {}, "jobs": {}, "executions": {}, "worker_sets": {}}
	if main_only:
		result["historical_orphans"] = {}
	job_ids, execution_keys = set(), set()
	for key in queues:
		queue = key.removeprefix("rq:queue:")
		result["queues"][queue] = listing(key)
		result["intermediate"][queue] = listing(key + ":intermediate")
		if not main_only:
			assert not result["intermediate"][queue], "Unexplained intermediate RQ jobs; HOLD"
		job_ids.update(result["queues"][queue])
		job_ids.update(result["intermediate"][queue])
		result["worker_sets"][queue] = members("rq:workers:" + queue)
		for kind in ("wip", "deferred", "scheduled", "finished", "failed", "canceled"):
			rows = registry("rq:" + kind + ":" + queue)
			result["registries"][kind + ":" + queue] = rows
			for member, _ in rows:
				if kind == "wip":
					assert member.count(":") == 1, "Malformed started execution ID; HOLD"
					job, execution = member.split(":")
					execution_keys.add("rq:execution:" + member)
					assert execution and job, "Empty started execution ID"
					job_ids.add(job)
				else:
					job_ids.add(member)
	if main_only:
		known_queues = set(queues) | {key + ":intermediate" for key in queues}
		for key in keys:
			if key.startswith("rq:queue:") and key not in known_queues:
				assert not listing(key), "Unknown/orphan live RQ queue; HOLD"
			if any(key.startswith("rq:" + kind + ":") for kind in ("wip", "deferred", "scheduled")) and key.removeprefix("rq:") not in result["registries"]:
				assert not registry(key), "Unknown/orphan live RQ registry; HOLD"
	worker_keys = members("rq:workers")
	assert all(key.startswith("rq:worker:") for key in worker_keys), "Malformed worker identity"
	for key in sorted({key for key in keys if key.startswith("rq:worker:")} | set(worker_keys)):
		worker = raw_hash(key)
		assert worker.get("pid") and worker.get("hostname") and worker.get("birth") and worker.get("state") in {"idle", "busy", "suspended"}, "Unknown/stale RQ worker; HOLD"
		if key in worker_keys:
			assert not worker.get("death"), "Registered dead worker; HOLD"
			result["workers"][key] = worker
			if worker.get("current_job"):
				job_ids.add(worker["current_job"])
		else:
			# Native register_death unregisters then retains the hash for 60s.
			# Only the caller's original matched worker may explain this tombstone.
			assert worker.get("death"), "Orphan/stale worker hash; HOLD"
			result["tombstones"][key] = worker
	job_ids.update(key.removeprefix("rq:job:") for key in keys if key.startswith("rq:job:"))
	for job in sorted(job_ids):
		assert job and ":" not in job, "Malformed RQ job ID"
		key = "rq:job:" + job
		if main_only and not typed(key, "hash"):
			historical = {name: [row for row in rows if row[0] == job] for name, rows in result["registries"].items() if name.startswith("finished:")}
			historical = {name: rows for name, rows in historical.items() if rows}
			live = any(job in rows for rows in (*result["queues"].values(), *result["intermediate"].values())) or any(worker.get("current_job") == job for worker in result["workers"].values()) or any(member.split(":", 1)[0] == job for name, rows in result["registries"].items() if not name.startswith("finished:") for member, _ in rows)
			assert historical and not live, "Referenced live/unknown job missing native data; HOLD"
			for name, rows in historical.items():
				result["historical_orphans"].setdefault(name, []).extend(rows)
			continue
		assert typed(key, "hash") and redis.hexists(key, "data"), "Referenced job missing native data; HOLD"
		assert all(redis.hstrlen(key, field) <= 4096 for field in JOB_FIELDS), "Job metadata exceeds bound"
		value = {field: decode(value) for field, value in zip(JOB_FIELDS, redis.hmget(key, JOB_FIELDS), strict=False)}
		assert value["origin"] in result["queues"] and value["status"] in {"queued", "started", "finished", "failed", "deferred", "scheduled", "canceled", "stopped"}, "Unknown job origin/status; HOLD"
		result["jobs"][job] = value
		for execution, _ in registry("rq:executions:" + job):
			execution_keys.add("rq:execution:" + job + ":" + execution)
	assert {key for key in keys if key.startswith("rq:execution:")} == execution_keys, "Orphan execution; HOLD"
	for key in sorted(execution_keys):
		result["executions"][key] = raw_hash(key)
	assert all(key in worker_keys for rows in result["worker_sets"].values() for key in rows), "Orphan queue worker registration"
	assert len(serialized(result)) <= 16 * 1024**2, "RQ complete inventory exceeds byte bound"
	return result


def assert_main_rq_empty(snapshot):
	"""Natural main-only drain; retain and report shared historical anomalies."""
	def live(job):
		assert any(job.startswith(site + "||") for site in SHARED_SITES), "Unknown live native job identity; HOLD"
		assert not job.startswith("deeplinkerp.com||"), "Live main native job/callback remains; HOLD"
	for rows in (*snapshot["queues"].values(), *snapshot.get("intermediate", {}).values()):
		for job in rows:
			live(job)
	for name, rows in snapshot["registries"].items():
		if name.startswith(("wip:", "deferred:", "scheduled:")):
			for member, _ in rows:
				live(member.split(":", 1)[0])
	for worker in snapshot["workers"].values():
		if worker.get("current_job"):
			live(worker["current_job"])
	for key in snapshot["executions"]:
		live(key.removeprefix("rq:execution:").split(":", 1)[0])
	for job, fact in snapshot["jobs"].items():
		if fact["status"] in {"queued", "started", "deferred", "scheduled"}:
			live(job)
	orphans = snapshot.get("historical_orphans", {})
	return {"main_empty": True, "historical_orphans": orphans, "shared_strict_hold": bool(orphans)}


def verify_rq_drain(before, after, completed):
	"""Preserve untouched queued/history state; only matched natural work may end."""
	assert not after["workers"] and not after["executions"], "Old RQ identities still active; HOLD"
	assert not any(rows for key, rows in after["registries"].items() if key.startswith("wip:")), "Started executions remain; HOLD"
	assert not before.get("tombstones"), "Unmatched pre-existing dead worker; HOLD"
	for key, worker in after.get("tombstones", {}).items():
		original = before["workers"].get(key)
		assert original and all(worker.get(field) == original.get(field) for field in ("pid", "hostname", "birth", "queues")), "Unmatched dead worker identity; HOLD"
		assert worker["death"] >= original["birth"], "Invalid native worker death; HOLD"
	for job, worker in completed.items():
		fact = after["jobs"].get(job)
		assert fact and fact["status"] == "finished" and fact["ended_at"] and fact["started_at"] and fact["worker_name"] == worker, "Natural job/callback completion unconfirmed; HOLD"
	for queue, jobs in before["queues"].items():
		assert [job for job in jobs if job not in completed] == [job for job in after["queues"][queue] if job in jobs and job not in completed], "Unmatched queued job vanished or reordered; HOLD"
	for kind, rows in before["registries"].items():
		if kind.startswith("wip:"):
			continue
		assert all(row in after["registries"].get(kind, []) for row in rows), "Historical RQ registry changed; HOLD"
	for job, fact in before["jobs"].items():
		if job not in completed:
			assert after["jobs"].get(job) == fact, "Unmatched job changed/vanished; HOLD"


def native_processes():
	"""Read PID/start-time/argv identities inside one known container namespace."""
	result = {}
	for path in Path("/proc").iterdir():
		if not path.name.isdigit():
			continue
		try:
			stat = (path / "stat").read_text().rsplit(")", 1)[1].split()
			argv = [value.decode() for value in (path / "cmdline").read_bytes().split(b"\0") if value]
			if argv:
				result[path.name] = {
					"pid": int(path.name),
					"parent": int(stat[1]),
					"start": stat[19],
					"argv": argv,
				}
		except FileNotFoundError:
			continue  # A concurrent natural exit is re-read by the caller.
	assert "1" in result and len(result) <= 100, "Unbounded/unknown container process inventory"
	return result


def _host_call(argv, *, timeout=30):
	return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=timeout).stdout


def _container_inspect(service):
	value = json.loads(_host_call(["docker", "inspect", "frappe_docker-" + service + "-1"]))
	assert len(value) == 1
	return value[0]


def _container_read(service, tool, action):
	return json.loads(_host_call(["docker", "exec", "frappe_docker-" + service + "-1", "/home/frappe/frappe-bench/env/bin/python", "/tmp/joint_release_guards.py", action]))


def _command_rq_snapshot(backend, tool):
	"""Reuse the read-only probe with the inspected image/network/sites identity."""
	sites_mounts = [item for item in backend["Mounts"] if item["Destination"] == "/home/frappe/frappe-bench/sites"]
	assert len(sites_mounts) == 1 and sites_mounts[0]["Type"] in {"bind", "volume"}, "Unknown shared sites mount"
	site_source = sites_mounts[0].get("Name") if sites_mounts[0]["Type"] == "volume" else sites_mounts[0]["Source"]
	return json.loads(_host_call(["docker", "run", "--rm", "--network", backend["HostConfig"]["NetworkMode"], "--mount", "type=bind,source=" + str(Path(tool).resolve()) + ",target=/tmp/joint_release_guards.py,readonly", "-v", site_source + ":/home/frappe/frappe-bench/sites:ro", "--entrypoint", "/home/frappe/frappe-bench/env/bin/python", backend["Image"], "/tmp/joint_release_guards.py", "--rq-snapshot"]))


def drain_release(path, tool, candidate_sha, *, timeout=360):
	"""One native TERM per fixed identity, bounded natural completion, no cleanup."""
	assert not Path(path).exists(), "Prior/unknown drain receipt exists; HOLD, do not signal twice"
	start = time.time()
	before = {"containers": {}, "processes": {}, "rq": _container_read("backend", tool, "--rq-snapshot"), "native": _container_read("backend", tool, "--runtime-proof"), "source_host": source_host_proof()}
	assert not before["rq"].get("tombstones"), "Unmatched prior native worker death; HOLD"
	for service in RELEASE_SERVICES:
		value = _container_inspect(service)
		assert value["State"]["Running"], "Old container not running; identity unknown"
		before["containers"][service] = {"id": value["Id"], "image": value["Image"], "pid": value["State"]["Pid"], "started": value["State"]["StartedAt"], "hostname": value["Config"]["Hostname"]}
		# nginx frontend lacks the Python runtime; its exact Docker PID/start still
		# belongs to the same old direct-entrypoint container.
		if service != "frontend":
			before["processes"][service] = _container_read(service, tool, "--processes")
	worker_names = {}
	for key, worker in before["rq"]["workers"].items():
		matches = [service for service in ("queue-long", "queue-short") if worker["hostname"] == before["containers"][service]["hostname"] and worker["pid"] == "1"]
		assert len(matches) == 1, "Unmatched/stale RQ worker process; HOLD"
		service = matches[0]
		assert "worker" in before["processes"][service]["1"]["argv"], "Worker is not the known direct PID1 entrypoint"
		assert service not in worker_names, "Multiple unknown workers in one container"
		worker_names[service] = key.removeprefix("rq:worker:")
	assert set(worker_names) == {"queue-long", "queue-short"}, "Missing native worker identity; HOLD"
	web = before["processes"]["backend"]
	assert any("gunicorn" in arg for arg in web["1"]["argv"]), "Unknown web entrypoint; HOLD"
	argv = web["1"]["argv"]
	assert not any(value in argv for value in ("sh", "bash", "-c", "--config", "-c")) and "frappe.app:application" in argv, "Unknown Gunicorn configuration/wrapper; HOLD"
	def option(names, default):
		found = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value in names]
		found += [value.split("=", 1)[1] for value in argv if value.split("=", 1)[0] in names and "=" in value]
		assert len(found) <= 1, "Ambiguous web option; HOLD"
		return found[0] if found else default
	assert (option(("--workers", "-w"), "1"), option(("--threads",), "1"), option(("--worker-class", "-k"), "sync"), option(("--timeout", "-t"), "30"), option(("--graceful-timeout",), "30")) == ("2", "4", "gthread", "120", "30") and "--preload" in argv, "Unreviewed actual Gunicorn drain configuration; HOLD"
	assert not any(value.startswith("GUNICORN_CMD_ARGS=") or value.startswith("GUNICORN_CONFIG=") for value in _container_inspect("backend")["Config"]["Env"]), "Unknown web environment options; HOLD"
	assert "schedule" in before["processes"]["scheduler"]["1"]["argv"], "Unknown native scheduler entrypoint; HOLD"
	assert Path(before["processes"]["websocket"]["1"]["argv"][0]).name == "node", "Realtime is not native direct PID1; HOLD"
	assert _host_call(["docker", "exec", "frappe_docker-websocket-1", "node", "--version"]).strip() == "v24.12.0", "Unknown realtime runtime; HOLD"
	web_children = [process for process in web.values() if process["parent"] == 1 and any("gunicorn" in arg for arg in process["argv"])]
	assert len(web_children) == 2, "Expected two known Gunicorn workers; HOLD"
	contract = {"container_ids": {service: value["id"] for service, value in before["containers"].items()}, "worker_names": worker_names, "one_term_only": True}
	identity = {"candidate_sha": candidate_sha, "contract_sha256": hashlib.sha256(serialized(contract)).hexdigest()}
	receipt = DDLReceipt.create(path, identity, before, contract)
	completed, last_rq = {}, before["rq"]
	def observe(snapshot):
		for job, value in snapshot["jobs"].items():
			if value["status"] == "started":
				assert value["worker_name"] in worker_names.values(), "Unmatched raced job; HOLD"
				completed[job] = value["worker_name"]
		for key in snapshot["executions"]:
			job = key.removeprefix("rq:execution:").split(":")[0]
			value = snapshot["jobs"][job]
			assert value["worker_name"] in worker_names.values(), "Unmatched native execution; HOLD"
			completed[job] = value["worker_name"]
	observe(last_rq)
	for service in ("scheduler", "frontend", "websocket", "queue-long", "queue-short", "backend"):
		value = _container_inspect(service)
		assert value["Id"] == before["containers"][service]["id"] and value["State"]["StartedAt"] == before["containers"][service]["started"] and value["State"]["Running"], "Process identity raced before TERM; HOLD"
		if service != "frontend":
			assert _container_read(service, tool, "--processes")["1"] == before["processes"][service]["1"], "PID/start/argv changed before TERM; HOLD"
		receipt.plan("term-" + service, {"signal_attempted": False}, {"signal_attempted": True}, kind="signal", identity=before["containers"][service])
		_host_call(["docker", "kill", "--signal", "TERM", value["Id"]])
		receipt.complete("term-" + service, {"signal_attempted": True})
	# Inspect Redis through a command-only old-image process after Gunicorn exits.
	# The helper is mounted read-only, sites/configs use the already-verified volume.
	backend = _container_inspect("backend")
	def stopped_snapshot():
		return _command_rq_snapshot(backend, tool)
	while time.time() - start < timeout:
		last_rq = stopped_snapshot()
		observe(last_rq)
		states = {service: _container_inspect(service) for service in RELEASE_SERVICES}
		assert all(value["Id"] == before["containers"][service]["id"] for service, value in states.items()), "Container identity changed during drain"
		if all(not value["State"]["Running"] for value in states.values()):
			break
		time.sleep(1)
	else:
		raise AssertionError("Bounded warm drain timed out; maintenance HOLD; no second signal")
	logs = {}
	for service, value in states.items():
		assert value["State"]["ExitCode"] in ({0} if service in {"backend", "queue-long", "queue-short", "frontend"} else {0, 143}), "Abnormal process exit; HOLD"
		assert not value["State"]["OOMKilled"] and not value["State"].get("Error"), "Killed/unconfirmed process; HOLD"
		log = subprocess.run(["docker", "logs", "--since", str(int(start)), value["Id"]], check=True, capture_output=True, text=True, timeout=30)
		logs[service] = log.stdout + log.stderr
		assert len(logs[service].encode()) <= 16 * 1024**2, "Native exit log proof exceeds bound; HOLD"
		logs[service] = re.sub(r"\x1b\[[0-9;]*m", "", logs[service])
		assert not re.search(r"SIGKILL|force.?stop|cold shutdown|killing.*horse|Worker.*timeout", logs[service], re.I), "Forced/unknown process shutdown; HOLD"
	for service in ("queue-long", "queue-short"):
		assert re.search(r"warm shut|warm stop", logs[service], re.I), "Missing native warm-shutdown proof; HOLD"
		for job in re.findall(r"Job OK\s*\(([^)]+)\)", logs[service]):
			if before["rq"]["jobs"].get(job, {}).get("status") != "finished":
				completed[job] = worker_names[service]
		for job, worker in completed.items():
			if worker == worker_names[service]:
				assert re.search(r"Job OK.*\(" + re.escape(job) + r"\)", logs[service]), "Missing native post-callback success log; HOLD"
	for process in web_children:
		assert re.search(r"Worker exiting.*\b" + str(process["pid"]) + r"\b", logs["backend"]), "Missing normal Gunicorn worker exit proof; HOLD"
	second = stopped_snapshot()
	assert second == last_rq, "Post-exit Redis inventory unstable; HOLD"
	verify_rq_drain(before["rq"], second, completed)
	receipt.finish({"containers": {service: {"id": value["Id"], "running": False, "exit_code": value["State"]["ExitCode"]} for service, value in states.items()}, "rq": second, "naturally_completed_jobs": completed, "native_logs": logs})
	return {"quiescent": True, "receipt": str(path), "one_term_per_identity": True}


def tenant_preflight(expected_erpnext, *, main_only=False):
	"""Read all tenants; plan only main full / secondary native-only metadata."""
	import erpnext
	import frappe
	import gunicorn
	import rq
	from procurement_release_metadata import (
		_capture_joint_state,
		_joint_plan,
		_read_only_native_planning,
		load_joint_contract,
		verify_current_joint_contract,
	)
	assert expected_erpnext and erpnext.__version__ == expected_erpnext, "Unknown/unapproved precise ERPNext version (actual " + erpnext.__version__ + "); HOLD"
	assert frappe.__version__ == "16.23.0" and rq.__version__ == "2.6.1" and gunicorn.__version__ == "23.0.0", "Unapproved native runtime; HOLD"
	bench = Path("/home/frappe/frappe-bench")
	result = {"versions": {"frappe": frappe.__version__, "erpnext": erpnext.__version__, "rq": rq.__version__, "gunicorn": gunicorn.__version__}, "sites": {}}
	for site in SHARED_SITES[:1] if main_only else SHARED_SITES:
		frappe.init(site=site, sites_path=str(bench / "sites"))
		frappe.connect()
		try:
			path = bench / "sites" / site / "site_config.json"
			assert not path.is_symlink(), "Unknown/shared tenant configuration target; HOLD"
			raw = path.read_bytes()
			config = json.loads(raw)
			installed = frappe.get_installed_apps()
			entry = {"installed_apps": installed, "configuration": config, "configuration_raw_base64": base64.b64encode(raw).decode(), "configuration_mode": path.stat().st_mode & 0o777, "maintenance_present": "maintenance_mode" in config, "maintenance_value": config.get("maintenance_mode")}
			assert frappe.db.sql("select version()")[0][0].startswith("11.8.6-"), "Production MariaDB 11.8.6 required; HOLD"
			if main_only:
				assert frappe.db.get_single_value("System Settings", "enable_scheduler") in (0, "0", False), (
					"Main global scheduler must remain disabled; HOLD"
				)
			if "deeplinkerp_branding" in installed:
				with _read_only_native_planning():
					native_only = site != "deeplinkerp.com"
					if not native_only:
						assert {"china_finance", "oa_purchase_request"} <= set(installed) and frappe.db.exists("DocType", "OA Purchase Request"), "Main requires actual Finance/OA installation; no auto-install; HOLD"
					contract = load_joint_contract(require_quiescent=False, native_only=native_only)
					current = _capture_joint_state(native_only=native_only)
					plan = _joint_plan(current, contract, when="preflight", seed="preflight", require_quiescent=False)
					entry.update(native_only=native_only, bounded_plan_definitions=plan["new_definitions"], audit=current)
			else:
				raise AssertionError(site + ": Branding not installed; no auto-install; HOLD")
			result["sites"][site] = entry
		finally:
			frappe.db.rollback()
			frappe.destroy()
	assert set(result["sites"]) == set(SHARED_SITES[:1] if main_only else SHARED_SITES)
	return result


def restore_site_maintenance(path, site, original, *, enable=False):
	"""Only the explicitly approved maintenance flag; preserve every other key."""
	assert site in SHARED_SITES
	config_path = Path(path) / site / "site_config.json"
	assert not config_path.is_symlink(), "Tenant configuration target changed; HOLD"
	config = json.loads(config_path.read_bytes())
	baseline = original["sites"][site]["configuration"]
	assert {key: value for key, value in config.items() if key != "maintenance_mode"} == {key: value for key, value in baseline.items() if key != "maintenance_mode"}, "Tenant configuration drift; HOLD"
	if enable:
		config["maintenance_mode"] = 1
	elif "maintenance_mode" in baseline:
		config["maintenance_mode"] = baseline["maintenance_mode"]
	else:
		config.pop("maintenance_mode", None)
	if enable:
		DDLReceipt(config_path, {})._save(config)
	else:
		assert json.loads(base64.b64decode(original["sites"][site]["configuration_raw_base64"])) == config
		DDLReceipt(config_path, {})._write(base64.b64decode(original["sites"][site]["configuration_raw_base64"]))
	os.chmod(config_path, original["sites"][site]["configuration_mode"])
	assert json.loads(config_path.read_bytes()) == config, "Maintenance read-back failed"


def source_host_proof():
	"""Inspect the existing runner only; never cancel/finalize/logging-snapshot."""
	root = Path("/home/yuewei/.local/state/deeplinkerp-source-sync")
	status = _host_call(["systemctl", "--user", "show", "deeplinkerp-source-sync.service", "--property=MainPID", "--property=Result", "--property=ActiveState", "--property=ExecMainStartTimestampMonotonic", "--property=ExecMainCode", "--property=ExecMainStatus"])
	values = dict(line.split("=", 1) for line in status.splitlines() if "=" in line)
	assert values.get("MainPID") == "0" and values.get("ActiveState") in {"inactive", "failed"} and values.get("Result") == "success", "Source host process/result unconfirmed; HOLD"
	for name in ("currentrun.json", "run.json"):
		path = root / name
		if path.exists():
			state = json.loads(path.read_bytes())
			assert not state.get("active") and not state.get("pid"), "Source runner durable active identity remains; HOLD"
			values[name] = state
	return values


def cleanup_owned_build(evidence, acceptance):
	"""The same release's one regenerable extraction tree, after real acceptance."""
	import shutil
	root = Path(evidence).resolve(strict=True)
	accepted = json.loads(Path(acceptance).read_bytes())
	owned = json.loads((root / "build-ownership.json").read_bytes())
	assert accepted.get("browser_accepted") is True and accepted["candidate_sha"] == owned["candidate_sha"] and accepted["image_id"] == owned["image_id"], "Actual online browser acceptance for this frozen release required"
	assert isinstance(accepted.get("loaded_assets"), list) and accepted["loaded_assets"], "Actual browser-loaded URLs/body SHA required"
	assert all(asset.get("url") and re.fullmatch(r"[0-9a-f]{64}", asset.get("body_sha256", "")) for asset in accepted["loaded_assets"])
	loaded = {asset["url"]: asset["body_sha256"] for asset in accepted["loaded_assets"]}
	assert all(loaded.get("https://deeplinkerp.com" + url) == digest for url, digest in owned["raw_assets"].items()), "Online browser origin/URL/body differs from frozen raw asset delivery; HOLD"
	path = Path(owned["path"])
	assert path.parent == Path("/tmp") and path.name.startswith("unified-purchase-build.") and not path.is_symlink()
	stats = path.stat()
	assert [stats.st_dev, stats.st_ino, stats.st_uid] == owned["identity"] and stats.st_uid == os.getuid(), "Build ownership/identity changed; HOLD"
	items = list(path.rglob("*"))
	for item in items:
		mode = item.lstat()
		assert stat.S_ISDIR(mode.st_mode) or (stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1), "Shared/linked/special extraction contents; HOLD"
	assert sorted(str(item.relative_to(path)) for item in items if item.is_dir()) == owned["directories"], "Build directory inventory changed; HOLD"
	assert (path / "release-source-manifest.json").is_file() and hashlib.sha256((path / "release-source-manifest.json").read_bytes()).hexdigest() == owned["manifest_sha256"]
	files = {str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest() for item in items if item.is_file()}
	assert files == owned["files"], "Build tree no longer contains only this release's exact regenerable files; HOLD"
	size = sum(item.stat().st_size for item in items if item.is_file())
	assert 0 < size <= owned["max_bytes"], "Unknown/unbounded extraction contents; HOLD"
	# Include stopped and unrelated containers: cache must be unused/unshared.
	container_ids = _host_call(["docker", "ps", "-aq"]).split()
	assert container_ids, "Unknown in-use/shared build inventory; HOLD"
	containers = json.loads(_host_call(["docker", "inspect", *container_ids]))
	canonical = path.resolve(strict=True)
	for container in containers:
		for mount in container["Mounts"]:
			source = Path(mount["Source"]).resolve()
			assert not (source == canonical or source in canonical.parents or canonical in source.parents), "Build tree in-use/shared by a container; HOLD"
	def health():
		backend = None
		if owned.get("lane") == "main-only":
			import sys
			helper = root / "main_site_lane.py"
			assert hashlib.sha256(helper.read_bytes()).hexdigest() == owned["main_helper_sha256"], "Frozen main health helper differs; forward HOLD"
			rq = json.loads(_host_call([sys.executable, str(helper), "health", "--evidence", str(root), "--build", str(root)]))
			assert rq.get("main_running") is True and rq.get("rq_aof") is True, "Main release health changed; forward HOLD"
			for site in SHARED_SITES[1:]:
				for url, digest in owned["old_raw_assets"].items():
					body = subprocess.run(["curl", "-fsS", "--max-time", "10", "https://" + site + url], check=True, capture_output=True, timeout=15).stdout
					assert hashlib.sha256(body).hexdigest() == digest, "Unrelated site's original raw asset body differs; forward HOLD"
		else:
			for service in RELEASE_SERVICES:
				value = _container_inspect(service)
				assert value["Image"] == owned["image_id"] and value["State"]["Running"] and not value["State"].get("OOMKilled"), "Release health/image changed; forward HOLD"
				if service == "backend":
					backend = value
		for site in SHARED_SITES:
			_host_call(["curl", "-fsS", "--max-time", "10", "https://" + site + "/api/method/ping"])
		for url, digest in owned["raw_assets"].items():
			body = subprocess.run(["curl", "-fsS", "--max-time", "10", "https://deeplinkerp.com" + url], check=True, capture_output=True, timeout=15).stdout
			assert hashlib.sha256(body).hexdigest() == digest, "Current raw asset body differs; forward HOLD"
		for image_id in (owned["image_id"], owned["rollback_image_id"]):
			assert json.loads(_host_call(["docker", "image", "inspect", image_id]))[0]["Id"] == image_id, "Current/rollback image retention unconfirmed; forward HOLD"
		if backend is not None:
			rq = _command_rq_snapshot(backend, Path(__file__))
			assert rq.get("redis_ping") is True and {"queues", "workers", "executions", "jobs", "registries"} <= set(rq), "Redis/RQ health unconfirmed; forward HOLD"
		return rq  # Running writers may naturally advance; record, never mutate/empty.
	before_rq = health()
	before = os.statvfs(path.parent)
	receipt_path = root / "cache-cleanup.json"
	identity = {"candidate_sha": owned["candidate_sha"], "contract_sha256": hashlib.sha256(serialized(owned)).hexdigest()}
	receipt = DDLReceipt.create(receipt_path, identity, {"available_bytes": before.f_bavail * before.f_frsize, "redis_rq": before_rq}, owned)
	receipt.plan("owned-build-cache", {"path": str(path), "exists": True, "bytes": size}, {"path": str(path), "exists": False}, kind="cache-cleanup")
	shutil.rmtree(path)  # exact validated owned artifact, never a Docker/image/volume prune
	receipt.complete("owned-build-cache", {"path": str(path), "exists": False})
	after = os.statvfs(path.parent)
	after_rq = health()
	receipt.finish({"removed_bytes": size, "available_bytes": after.f_bavail * after.f_frsize, "health": "verified", "redis_rq": after_rq, "retained_images": [owned["image_id"], owned["rollback_image_id"]]})
	return receipt.state["after"]


class DDLReceipt:
	"""The first baseline and every intent survive each MariaDB autocommit.

	A pending step may already exist after a crash. Recovery must inspect the DB.
	The release lock and worker quiescence are held by the existing shell caller.
	"""

	def __init__(self, path, state):
		self.path, self.state = Path(path), state

	@classmethod
	def create(cls, path, identity, before, contract):
		validate_identity(identity)
		state = {"identity": copy.deepcopy(identity), "before": copy.deepcopy(before),
			"before_sha256": hashlib.sha256(serialized(before)).hexdigest(),
			"contract": copy.deepcopy(contract), "contract_sha256": hashlib.sha256(serialized(contract)).hexdigest(),
			"steps": [], "status": "applying"}
		path = Path(path)
		fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
		with os.fdopen(fd, "wb") as output:
			output.write(serialized(state))
			output.flush()
			os.fsync(output.fileno())
		cls._sync_directory(path.parent)
		return cls(path, state)

	@classmethod
	def load(cls, path, identity=None):
		state = json.loads(Path(path).read_bytes())
		validate_identity(state["identity"])
		if identity is not None:
			validate_identity(identity)
			assert state["identity"] == identity, "Receipt belongs to another frozen release"
		assert state["before_sha256"] == hashlib.sha256(serialized(state["before"])).hexdigest(), "Receipt baseline drift"
		assert state["contract_sha256"] == hashlib.sha256(serialized(state["contract"])).hexdigest(), "Receipt contract drift"
		return cls(path, state)

	@staticmethod
	def _sync_directory(directory):
		fd = os.open(directory, os.O_RDONLY)
		try:
			os.fsync(fd)
		finally:
			os.close(fd)

	def _save(self, state):
		self._write(serialized(state))
		self.state = state

	def _write(self, content):
		fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
		try:
			with os.fdopen(fd, "wb") as output:
				output.write(content)
				output.flush()
				os.fsync(output.fileno())
			os.replace(temporary, self.path)
			self._sync_directory(self.path.parent)
		finally:
			if os.path.exists(temporary):
				os.unlink(temporary)

	def plan(self, step_id, before, expected_after, **details):
		assert step_id and before != expected_after, "No-op must not create a receipt step"
		step = {"id": step_id, "before": copy.deepcopy(before), "expected_after": copy.deepcopy(expected_after), "status": "pending", **details}
		for existing in self.state["steps"]:
			if existing["id"] == step_id:
				assert {k: v for k, v in existing.items() if k not in {"status", "actual"}} == {k: v for k, v in step.items() if k != "status"}
				return
		state = copy.deepcopy(self.state)
		state["steps"].append(step)
		self._save(state)

	def complete(self, step_id, actual):
		state = copy.deepcopy(self.state)
		step = next(item for item in state["steps"] if item["id"] == step_id)
		assert actual == step["expected_after"], "Mutation differs from recorded exact scope"
		if step["status"] == "complete":
			return
		step.update(status="complete", actual=copy.deepcopy(actual))
		self._save(state)

	def finish(self, after):
		if self.state["status"] == "applied":
			assert self.state["after"] == after, "Identical apply drift"
			return
		assert all(step["status"] == "complete" for step in self.state["steps"])
		state = copy.deepcopy(self.state)
		state.update(status="applied", after=copy.deepcopy(after))
		self._save(state)

	def restored(self):
		if self.state["status"] != "restored":
			state = copy.deepcopy(self.state)
			state["status"] = "restored"
			self._save(state)


def main():
	import argparse
	parser = argparse.ArgumentParser(description="Bounded guards for the existing procurement release")
	action = parser.add_mutually_exclusive_group(required=True)
	for name in ("rq-snapshot", "rq-main-snapshot", "processes", "runtime-proof", "tenant-preflight", "source-host-proof", "host-drain", "record-resume", "assert-pre-resume", "maintenance-on", "maintenance-restore", "cleanup-owned-build"):
		action.add_argument("--" + name, action="store_true")
	parser.add_argument("--receipt")
	parser.add_argument("--candidate-sha")
	parser.add_argument("--image-id")
	parser.add_argument("--producer")
	parser.add_argument("--erpnext-version")
	parser.add_argument("--tenant-receipt")
	parser.add_argument("--evidence")
	parser.add_argument("--acceptance")
	parser.add_argument("--main-only", action="store_true")
	args = parser.parse_args()
	if args.rq_snapshot or args.rq_main_snapshot:
		import redis
		import rq
		assert rq.__version__ == "2.6.1", "RQ native source version unknown; HOLD"
		config = json.loads(Path("/home/frappe/frappe-bench/sites/common_site_config.json").read_bytes())
		client = redis.Redis.from_url(config["redis_queue"], socket_connect_timeout=5, socket_timeout=5)
		assert client.ping() is True, "Redis health unconfirmed; HOLD"
		result = raw_rq_snapshot(client, main_only=args.rq_main_snapshot)
		result["redis_ping"] = True
	elif args.processes:
		result = native_processes()
	elif args.runtime_proof:
		result = native_runtime_proof()
	elif args.tenant_preflight:
		result = tenant_preflight(args.erpnext_version, main_only=args.main_only)
	elif args.source_host_proof:
		result = source_host_proof()
	elif args.host_drain:
		result = drain_release(args.receipt, str(Path(__file__).resolve()), args.candidate_sha)
	elif args.record_resume:
		result = record_resume(
			args.receipt, {"candidate_sha": args.candidate_sha, "image_id": args.image_id}, args.producer
		)
	elif args.assert_pre_resume:
		assert_pre_resume(args.receipt)
		result = {"pre_resume": True}
	elif args.maintenance_on or args.maintenance_restore:
		original = json.loads(Path(args.tenant_receipt).read_bytes())
		for site in SHARED_SITES:
			restore_site_maintenance(
				"/home/frappe/frappe-bench/sites", site, original, enable=args.maintenance_on
			)
		result = {"sites": list(SHARED_SITES), "maintenance": "on" if args.maintenance_on else "restored"}
	elif args.cleanup_owned_build:
		result = cleanup_owned_build(args.evidence, args.acceptance)
	else:
		raise AssertionError("Unrecognized release action")
	print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
	main()
