"""Pure bounded-schema and durable-receipt guards; no database writes here."""

import copy
import hashlib
import json
import os
import re
import tempfile
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
		fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
		try:
			with os.fdopen(fd, "wb") as output:
				output.write(serialized(state))
				output.flush()
				os.fsync(output.fileno())
			os.replace(temporary, self.path)
			self._sync_directory(self.path.parent)
			self.state = state
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
