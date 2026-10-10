"""One-time main site namespace/authentication/route split; no business metadata."""

import base64
import grp
import hashlib
import json
import os
import pwd
import re
import secrets
import subprocess
import sys
import time
import traceback
from pathlib import Path

from joint_release_guards import (
	RELEASE_SERVICES,
	SHARED_SITES,
	DDLReceipt,
	assert_main_rq_empty,
	serialized,
	source_host_proof,
	validate_main_seal,
)

BENCH = "/home/frappe/frappe-bench"
SITE = "deeplinkerp.com"
PROJECT = "deeplinkerp_main"
NETWORK = "frappe_docker_default"
SITES_VOLUME = "frappe_docker_sites"
DB_CONTAINER = "frappe_docker-db-1"
ROUTE_TARGET = "/etc/nginx/conf.d/deeplinkerp-main.conf"
CONTAINER_IDENTITY_FIELDS = (
	"id",
	"image",
	"pid",
	"started",
	"running",
	"config_format",
	"config_sha256",
	"networks",
)


def frontend_bind(source, binding):
	"""Insert one mount without serializing/reformatting the owner's dirty YAML."""
	assert binding.encode() not in source, "Main route is already managed; HOLD"
	matches = list(re.finditer(rb"(?m)^  frontend:\s*\n", source))
	assert len(matches) == 1, "Unknown frontend Compose shape; HOLD"
	start = matches[0].end()
	end = re.search(rb"(?m)^(?:  [a-zA-Z0-9_-]+:|[^ #\r\n])", source[start:])
	stop = start + end.start() if end else len(source)
	section = source[start:stop]
	volumes = list(re.finditer(rb"(?m)^    volumes:\s*\n", section))
	assert len(volumes) <= 1 and not re.search(rb"(?m)^    (?:extends|<<):", section), (
		"Unknown frontend volume inheritance; HOLD"
	)
	position = start + volumes[0].end() if volumes else stop
	addition = ("      - " + json.dumps(binding) + "\n").encode()
	if not volumes:
		addition = b"    volumes:\n" + addition
	return source[:position] + addition + source[position:]


def main_route(*, maintenance):
	if maintenance:
		return "server {\n  listen 8080;\n  server_name deeplinkerp.com;\n  add_header Retry-After 120 always;\n  return 503;\n}\n"
	return """map $http_upgrade $dlp_main_connection { default upgrade; '' close; }
server {
  listen 8080;
  server_name deeplinkerp.com;
  resolver 127.0.0.11 valid=10s;
  set $dlp_main_frontend http://deeplinkerp_main-frontend-1:8080;
  client_max_body_size 50m;
  location / {
    proxy_pass $dlp_main_frontend;
    proxy_http_version 1.1;
    proxy_set_header Host deeplinkerp.com;
    proxy_set_header X-Frappe-Site-Name deeplinkerp.com;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $dlp_main_connection;
    proxy_read_timeout 120s;
  }
}
"""


def lane_compose(image, redis_image, evidence, subpath, *, private_gid=None):
	root = str(Path(evidence).resolve())
	private_gid = os.getgid() if private_gid is None else private_gid
	assert re.fullmatch(r"\.deeplinkerp-main-lane/[a-zA-Z0-9_-]+/deeplinkerp\.com", subpath)
	mounts = [
		{"type": "bind", "source": root + "/main-sites", "target": BENCH + "/sites"},
		{
			"type": "volume",
			"source": "sites",
			"target": BENCH + "/sites/" + SITE,
			"volume": {"subpath": subpath},
		},
		{
			"type": "bind",
			"source": root + "/main-site-config.json",
			"target": BENCH + "/sites/" + SITE + "/site_config.json",
			"read_only": True,
		},
	]
	specs = {
		"backend": (None, 1024**3),
		"frontend": (["nginx-entrypoint.sh"], 128 * 1024**2),
		"websocket": (["node", BENCH + "/apps/frappe/socketio.js"], 256 * 1024**2),
		"queue-long": (["bench", "worker", "--queue", "long,default,short"], 768 * 1024**2),
		"queue-short": (["bench", "worker", "--queue", "short,default"], 512 * 1024**2),
		"redis-queue": (
			[
				"redis-server",
				"--save",
				"",
				"--appendonly",
				"yes",
				"--appendfsync",
				"everysec",
				"--maxmemory",
				"96mb",
				"--maxmemory-policy",
				"noeviction",
			],
			128 * 1024**2,
		),
		"redis-cache": (
			[
				"redis-server",
				"--save",
				"",
				"--appendonly",
				"no",
				"--maxmemory",
				"96mb",
				"--maxmemory-policy",
				"allkeys-lru",
			],
			128 * 1024**2,
		),
	}
	services = {}
	for name, (command, memory) in specs.items():
		value = {
			"image": redis_image if name.startswith("redis-") else image,
			"container_name": PROJECT + "-" + name + "-1",
			"restart": "unless-stopped",
			"mem_limit": memory,
		}
		if command:
			value["command"] = command
		if not name.startswith("redis-"):
			value["volumes"] = mounts
			value["group_add"] = [str(private_gid)]
		if name == "redis-queue":
			value["volumes"] = [{"type": "volume", "source": "main-rq", "target": "/data"}]
		if name == "frontend":
			value["environment"] = {
				"BACKEND": PROJECT + "-backend-1:8000",
				"SOCKETIO": PROJECT + "-websocket-1:9000",
				"FRAPPE_SITE_NAME_HEADER": SITE,
				"UPSTREAM_REAL_IP_ADDRESS": "127.0.0.1",
				"UPSTREAM_REAL_IP_HEADER": "X-Forwarded-For",
				"UPSTREAM_REAL_IP_RECURSIVE": "off",
			}
		services["main-" + name] = value
	return {
		"services": services,
		"networks": {"default": {"external": True, "name": NETWORK}},
		"volumes": {
			"sites": {"external": True, "name": SITES_VOLUME},
			"main-rq": {"name": "deeplinkerp_main_rq"},
		},
	}


def db_call(sql):
	# Root credentials stay inside the normal DB container and never enter logs.
	result = subprocess.run(
		[
			"docker",
			"exec",
			"-i",
			DB_CONTAINER,
			"sh",
			"-c",
			'exec mariadb --user=root --password="${MARIADB_ROOT_PASSWORD:-$MYSQL_ROOT_PASSWORD}" --batch --raw --skip-column-names',
		],
		input=sql,
		capture_output=True,
		text=True,
		timeout=30,
	)
	if result.returncode:
		raise RuntimeError("Scoped DB administration failed; main maintenance HOLD")
	return result.stdout


def sql_literal(value):
	assert "\0" not in value and "\\" not in value
	return "'" + value.replace("'", "''") + "'"


def account_snapshot(user):
	assert re.fullmatch(r"[A-Za-z0-9_]+", user)
	rows = db_call(
		"SELECT JSON_OBJECT('user',User,'host',Host,'priv',JSON_EXTRACT(Priv,'$')) FROM mysql.global_priv WHERE User="
		+ sql_literal(user)
		+ " ORDER BY Host;"
	)
	accounts = [json.loads(row) for row in rows.splitlines() if row]
	for account in accounts:
		account["grants"] = db_call(
			"SHOW GRANTS FOR " + sql_literal(user) + "@" + sql_literal(account["host"]) + ";"
		).splitlines()
	return accounts


def validate_accounts(accounts, user, database):
	assert accounts and re.fullmatch(r"[A-Za-z0-9_]+", database)
	assert len({entry["host"] for entry in accounts}) == len(accounts)
	for account in accounts:
		assert account["user"] == user and not account["priv"].get("account_locked"), (
			"Original main account identity/lock drift; HOLD"
		)
		assert len(account["grants"]) == 2, "Unexpected original main role/proxy/table grants; HOLD"
		grants = [row.split(" TO ", 1)[0].replace("\\_", "_") for row in account["grants"]]
		assert set(grants) == {"GRANT USAGE ON *.*", "GRANT ALL PRIVILEGES ON `" + database + "`.*"}, (
			"Original main account authorizes another DB/scope; HOLD"
		)
		assert not any("WITH GRANT OPTION" in row for row in account["grants"]), (
			"Main grant option forbidden; HOLD"
		)


def lock_accounts(receipt, accounts):
	for account in accounts:
		after = {**account, "priv": {**account["priv"], "account_locked": True}}
		step = "lock-old-" + account["host"]
		receipt.plan(step, account, after, kind="authentication")
		db_call(
			"ALTER USER "
			+ sql_literal(account["user"])
			+ "@"
			+ sql_literal(account["host"])
			+ " ACCOUNT LOCK;"
		)
		actual = next(
			value for value in account_snapshot(account["user"]) if value["host"] == account["host"]
		)
		# SHOW GRANTS includes ACCOUNT LOCK only on some server versions.
		assert actual["priv"] == after["priv"], "Main account lock read-back differs; HOLD"
		receipt.complete(step, after)


def site_boundary(root, action, subpath, original=None):
	"""Run only in a command container on the existing volume, same inode/files."""
	root = Path(root)
	assert re.fullmatch(r"\.deeplinkerp-main-lane/[a-zA-Z0-9_-]+/deeplinkerp\.com", subpath)
	assets = root / "assets"
	assert assets.is_symlink() and os.readlink(assets) == BENCH + "/assets", (
		"Shared asset root alias differs from the fixed image path; HOLD"
	)
	src, dst = root / SITE, root / subpath
	discovered = sorted(
		path.name
		for path in root.iterdir()
		if path.is_dir() and not path.is_symlink() and (path / "site_config.json").is_file()
	)
	if action == "snapshot":
		assert discovered == sorted(SHARED_SITES), "Unknown sites volume discovery; HOLD"
		assert src.is_dir() and not src.is_symlink() and not dst.exists()
		configs = {}
		for site in SHARED_SITES:
			path = root / site / "site_config.json"
			assert not path.is_symlink() and path.stat().st_nlink == 1, "Shared/linked site config; HOLD"
			configs[site] = base64.b64encode(path.read_bytes()).decode()
		stats = src.stat()
		return {
			"configs": configs,
			"assets_link": os.readlink(assets),
			"config_mode": (src / "site_config.json").stat().st_mode & 0o777,
			"directory_identity": [stats.st_dev, stats.st_ino],
			"common": base64.b64encode((root / "common_site_config.json").read_bytes()).decode(),
			"apps": base64.b64encode((root / "apps.txt").read_bytes()).decode(),
		}
	assert original
	for site in SHARED_SITES[1:]:
		assert (root / site / "site_config.json").read_bytes() == base64.b64decode(
			original["configs"][site]
		), "Unrelated site config changed; HOLD"
	assert (root / "common_site_config.json").read_bytes() == base64.b64decode(original["common"]) and (
		root / "apps.txt"
	).read_bytes() == base64.b64decode(original["apps"]), "Shared common/apps changed; HOLD"
	if action == "maintenance":
		path = src / "site_config.json"
		assert path.read_bytes() == base64.b64decode(original["configs"][SITE])
		value = json.loads(path.read_bytes())
		value["maintenance_mode"] = 1
		DDLReceipt(path, {})._write(serialized(value))
		os.chmod(path, original["config_mode"])
	elif action == "relocate":
		assert src.is_dir() and not src.is_symlink() and not dst.exists()
		assert json.loads((src / "site_config.json").read_bytes())["maintenance_mode"] == 1
		dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
		assert dst.parent.stat().st_dev == src.stat().st_dev, "Cross-filesystem relocation forbidden"
		os.rename(src, dst)
		DDLReceipt._sync_directory(root)
		DDLReceipt._sync_directory(dst.parent)
	elif action == "restore":
		assert src.exists() != dst.exists(), "Original site location ambiguous; HOLD"
		if dst.exists():
			assert not dst.is_symlink() and dst.stat().st_dev == root.stat().st_dev
			os.rename(dst, src)
			DDLReceipt._sync_directory(root)
			DDLReceipt._sync_directory(dst.parent)
		DDLReceipt(src / "site_config.json", {})._write(base64.b64decode(original["configs"][SITE]))
		os.chmod(src / "site_config.json", original["config_mode"])
	elif action != "proof":
		raise AssertionError("Unknown fixed volume action")
	current = dst if dst.exists() else src
	assert (
		not current.is_symlink()
		and [current.stat().st_dev, current.stat().st_ino] == original["directory_identity"]
	), "Original site inode changed; HOLD"
	config = json.loads((current / "site_config.json").read_bytes())
	old = json.loads(base64.b64decode(original["configs"][SITE]))
	assert {key: value for key, value in config.items() if key != "maintenance_mode"} == {
		key: value for key, value in old.items() if key != "maintenance_mode"
	}, "Original credential/config changed; HOLD"
	return {
		"directory_identity": original["directory_identity"],
		"location": subpath if dst.exists() else SITE,
		"maintenance_mode": config.get("maintenance_mode"),
		"discovered_sites": sorted(
			path.name
			for path in root.iterdir()
			if path.is_dir() and not path.is_symlink() and (path / "site_config.json").is_file()
		),
	}


def asset_view(bench):
	"""Read immutable compiled assets in the image, not a host-resolved volume alias."""
	bench = Path(bench)
	assets = bench / "assets"
	assert assets.is_dir() and not assets.is_symlink(), "Unknown physical image asset root; HOLD"
	links = {}
	for path in assets.iterdir():
		if not path.is_symlink():
			continue
		app = path.name
		assert re.fullmatch(r"[a-zA-Z0-9_]+", app)
		expected = bench / "apps" / app / app / "public"
		target = os.readlink(path)
		assert target in {str(expected), "../apps/" + app + "/" + app + "/public"}, (
			"Unknown asset symlink target; HOLD"
		)
		assert path.resolve(strict=True) == expected.resolve(strict=True) and expected.is_dir(), (
			"Asset symlink resolves outside exact image app; HOLD"
		)
		links[app] = target
	assert links, "No provable image asset symlinks; HOLD"
	manifest = (assets / "assets.json").read_bytes()

	def urls(value):
		if isinstance(value, str):
			return [value]
		if isinstance(value, dict):
			return [url for item in value.values() for url in urls(item)]
		assert isinstance(value, list), "Unknown asset manifest value"
		return [url for item in value for url in urls(item)]

	bodies = {}
	for url in urls(json.loads(manifest)):
		assert url.startswith("/assets/") and ".." not in Path(url).parts and "?" not in url, (
			"Unknown asset manifest URL"
		)
		path = assets / url.removeprefix("/assets/")
		app = url.removeprefix("/assets/").split("/", 1)[0]
		assert app in links and path.resolve(strict=True).is_relative_to(
			(bench / "apps" / app / app / "public").resolve()
		), "Asset manifest escapes image app"
		bodies[url] = hashlib.sha256(path.read_bytes()).hexdigest()
	return {
		"links": links,
		"manifest_sha256": hashlib.sha256(manifest).hexdigest(),
		"manifest_bodies": bodies,
	}


def frozen_model(root, receipt):
	assets = root / "main-sites/assets"
	assert (
		not assets.parent.is_symlink() and assets.is_symlink() and os.readlink(assets) == BENCH + "/assets"
	), "Private asset root alias differs from the frozen image path; HOLD"
	model = json.loads((root / "main.compose.json").read_bytes())
	contract = receipt.state["contract"]
	assert model == lane_compose(
		contract["image_id"],
		contract["redis_image_id"],
		root,
		contract["subpath"],
		private_gid=contract["private_gid"],
	), "Main Compose topology differs from its frozen receipt; HOLD"
	return model


def runner_command(evidence, build, image, entrypoint, argv, candidate_sha):
	root = Path(evidence).resolve()
	access = runtime_access(root)
	receipt = DDLReceipt.load(root / "main-seal.json")
	assert candidate_sha == receipt.state["identity"]["candidate_sha"] and image in {
		receipt.state["contract"]["base_image"],
		receipt.state["contract"]["image_id"],
	}, "Unknown bounded main runner image/identity; HOLD"
	model = frozen_model(root, receipt)
	assert access["private_gid"] == receipt.state["contract"]["private_gid"], (
		"Private runtime group drift; HOLD"
	)
	command = [
		"docker",
		"run",
		"--rm",
		"--read-only",
		"--group-add",
		str(access["private_gid"]),
		"--network",
		NETWORK,
		"--workdir",
		BENCH + "/sites",
		"--tmpfs",
		"/tmp",
	]
	for mount in model["services"]["main-backend"]["volumes"]:
		value = (
			"type="
			+ mount["type"]
			+ ",source="
			+ (SITES_VOLUME if mount["type"] == "volume" else mount["source"])
			+ ",target="
			+ mount["target"]
		)
		if mount.get("volume", {}).get("subpath"):
			value += ",volume-subpath=" + mount["volume"]["subpath"]
		if mount.get("read_only"):
			value += ",readonly"
		command += ["--mount", value]
	command += [
		"--mount",
		"type=bind,source=" + str(Path(build).resolve()) + ",target=/release,readonly",
		"--mount",
		"type=bind,source=" + str(root) + ",target=/release-evidence,readonly",
		"-e",
		"FRAPPE_STREAM_LOGGING=1",
		"-e",
		"DEEPLINKERP_RELEASE_CANDIDATE_SHA=" + candidate_sha,
		"-e",
		"DEEPLINKERP_MAIN_SEAL_RECEIPT=/release-evidence/main-seal.json",
		"-e",
		"DEEPLINKERP_MAIN_SEAL_PROOF=/release-evidence/main-seal-proof.json",
		"-e",
		"DEEPLINKERP_RELEASE_RESUME_RECEIPT="
		+ BENCH
		+ "/sites/"
		+ SITE
		+ "/private/release-evidence/joint-"
		+ candidate_sha[:12]
		+ ".resume.json",
		"--entrypoint",
		entrypoint,
		image,
		*argv,
	]
	return command


def host_call(argv, *, payload=None, timeout=30):
	result = subprocess.run(argv, input=payload, check=False, capture_output=True, text=True, timeout=timeout)
	if result.returncode:
		# Account/config payloads can contain credentials. Never echo stderr or
		# command output into release logs when a control action fails.
		raise RuntimeError("Main isolation control action failed; maintenance HOLD")
	return result.stdout


def inspect(container):
	values = json.loads(host_call(["docker", "inspect", container]))
	assert len(values) == 1
	return values[0]


def container_identity(value, *, legacy_config_sha256=None):
	"""Only Docker's unordered Mounts list is normalized; every field stays hashed."""
	mounts = value["Mounts"]
	assert isinstance(mounts, list) and all(
		isinstance(mount, dict)
		and isinstance(mount.get("Destination"), str)
		and mount["Destination"].startswith("/")
		for mount in mounts
	), "Unknown Docker Mounts shape; HOLD"
	destinations = {mount["Destination"] for mount in mounts}
	assert len(destinations) == len(mounts), "Duplicate Docker mount destinations; HOLD"
	ordered = sorted(mounts, key=lambda mount: mount["Destination"])
	configuration = {"Config": value["Config"], "HostConfig": value["HostConfig"], "Mounts": ordered}
	identity = {
		"id": value["Id"],
		"image": value["Image"],
		"pid": value["State"]["Pid"],
		"started": value["State"]["StartedAt"],
		"running": value["State"]["Running"],
		"config_format": "mounts-by-destination-v1",
		"config_sha256": hashlib.sha256(serialized(configuration)).hexdigest(),
		"networks": value["NetworkSettings"]["Networks"],
	}
	if legacy_config_sha256 is not None:
		# Pre-version receipts recorded exactly logs/sites in either Docker order.
		# Restore-only compatibility, removable once these receipts are restored.
		assert destinations == {BENCH + "/logs", BENCH + "/sites"}, "Unknown legacy Docker mount scope; HOLD"
		alternate = hashlib.sha256(serialized({**configuration, "Mounts": ordered[::-1]})).hexdigest()
		identity.pop("config_format")
		if legacy_config_sha256 in {identity["config_sha256"], alternate}:
			identity["config_sha256"] = legacy_config_sha256
	return identity


def assert_original_processes(expected, reason, *, allow_legacy_mount_order=False):
	current = {}
	for service in RELEASE_SERVICES:
		previous = expected.get(service, {})
		legacy_sha = (
			previous.get("config_sha256")
			if allow_legacy_mount_order and "config_format" not in previous
			else None
		)
		value = inspect("frappe_docker-" + service + "-1")
		current[service] = (
			container_identity(value, legacy_config_sha256=legacy_sha)
			if legacy_sha is not None
			else container_identity(value)
		)
	if current == expected:
		return
	error = AssertionError(reason)
	error.original_process_changes = {
		service: [
			field
			for field in CONTAINER_IDENTITY_FIELDS
			if current[service].get(field) != expected.get(service, {}).get(field)
		]
		for service in RELEASE_SERVICES
		if current[service] != expected.get(service)
	}
	raise error


def wait_main_maintenance(*, timeout=30):
	"""Nginx reload is asynchronous: require all paths in one fresh, bounded round."""
	deadline = time.monotonic() + timeout
	urls = (
		"/api/method/ping",
		"/assets/frappe/js/frappe-web.bundle.js",
		"/files/main-seal",
		"/protected/main-seal",
		"/socket.io/",
	)
	while True:
		statuses = []
		for url in urls:
			remaining = deadline - time.monotonic()
			assert remaining > 0, "Main all-URL maintenance route unconfirmed; HOLD"
			bound = min(2, remaining)
			try:
				statuses.append(
					host_call(
						[
							"curl",
							"-sS",
							"--max-time",
							str(bound),
							"-o",
							"/dev/null",
							"-w",
							"%{http_code}",
							"-H",
							"Host: " + SITE,
							"http://127.0.0.1:8888" + url,
						],
						timeout=bound,
					)
				)
			except (RuntimeError, subprocess.TimeoutExpired):
				statuses.append(None)
		remaining = deadline - time.monotonic()
		assert remaining > 0, "Main all-URL maintenance route unconfirmed; HOLD"
		if all(status == "503" for status in statuses):
			return
		time.sleep(min(0.25, remaining))


def assert_private_host_boundary(root, containers):
	root = Path(root).resolve(strict=True)
	for container in containers:
		for mount in container["Mounts"]:
			assert mount["Type"] in {"bind", "volume"} and mount["Source"], (
				"Unknown original host mount; HOLD"
			)
			source = Path(mount["Source"]).resolve()
			assert source != root and source not in root.parents, (
				"Old container can reach new host-private credentials; HOLD"
			)


def image_call(image, build, action, *, payload=None, writable=False, assets_only=False):
	tools = Path(build).resolve()
	if (tools / "deploy/production").is_dir():
		tools = tools / "deploy/production"
	else:
		runtime_access(tools)
	assert (tools / "main_site_lane.py").is_file() and (tools / "joint_release_guards.py").is_file(), (
		"Frozen main inspection tools missing; HOLD"
	)
	mounts = (
		[]
		if assets_only
		else [
			"--mount",
			"type=volume,source="
			+ SITES_VOLUME
			+ ",target="
			+ BENCH
			+ "/sites"
			+ ("" if writable else ",readonly"),
		]
	)
	return json.loads(
		host_call(
			[
				"docker",
				"run",
				"-i",
				"--rm",
				"--read-only",
				"--group-add",
				str(os.getgid()),
				"--network",
				"none",
				"--tmpfs",
				"/tmp",
				"--mount",
				"type=bind,source=" + str(tools) + ",target=/release-tools,readonly",
				*mounts,
				"--entrypoint",
				BENCH + "/env/bin/python",
				image,
				"/release-tools/main_site_lane.py",
				action,
			],
			payload=json.dumps(payload or {}),
		)
	)


def volume_call(receipt, build, action):
	return image_call(
		receipt.state["contract"]["base_image"],
		build,
		"volume",
		payload={
			"action": action,
			"subpath": receipt.state["contract"]["subpath"],
			"original": receipt.state["before"]["volume"],
		},
		writable=action in {"maintenance", "relocate", "restore"},
	)


def compose(evidence, *args):
	roles = {"backend", "frontend", "websocket", "queue-long", "queue-short", "redis-queue", "redis-cache"}
	args = ["main-" + value if value in roles else value for value in args]
	return host_call(
		[
			"docker",
			"compose",
			"-p",
			PROJECT,
			"-f",
			str(Path(evidence).resolve() / "main.compose.json"),
			*args,
		],
		timeout=90,
	)


def install_route(receipt, *, maintenance, first=False):
	contract = receipt.state["contract"]
	route, compose_path = Path(contract["route_path"]), Path(contract["compose_path"])
	source = base64.b64decode(receipt.state["before"]["compose"])
	binding = str(route) + ":" + ROUTE_TARGET + ":ro"
	changed = frontend_bind(source, binding)
	content = main_route(maintenance=maintenance).encode()
	if first:
		assert not route.exists() and compose_path.read_bytes() == source, "Route/dirty Compose drift; HOLD"
	else:
		assert compose_path.read_bytes() == changed, "Future managed frontend binding drift; HOLD"
	before = {
		"route_sha256": hashlib.sha256(route.read_bytes()).hexdigest() if route.exists() else None,
		"compose_sha256": hashlib.sha256(compose_path.read_bytes()).hexdigest(),
	}
	after = {
		"route_sha256": hashlib.sha256(content).hexdigest(),
		"compose_sha256": hashlib.sha256(changed).hexdigest(),
	}
	step = "route-maintenance-first" if first else ("route-hold" if maintenance else "route-candidate")
	if before != after:
		receipt.plan(step, before, after, kind="route")
	route.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
	assert not route.is_symlink() and not compose_path.is_symlink()
	DDLReceipt(route, {})._write(content)
	os.chmod(route, 0o644)  # Static routing only; no credentials or audit data.
	if first:
		mode = compose_path.stat().st_mode & 0o777
		DDLReceipt(compose_path, {})._write(changed)
		os.chmod(compose_path, mode)
		host_call(["docker", "compose", "-p", "frappe_docker", "-f", str(compose_path), "config", "--quiet"])
	host_call(["docker", "cp", str(route), "frappe_docker-frontend-1:" + ROUTE_TARGET])
	host_call(["docker", "exec", "frappe_docker-frontend-1", "nginx", "-t"])
	host_call(["docker", "exec", "frappe_docker-frontend-1", "nginx", "-s", "reload"])
	if before != after:
		receipt.complete(step, after)


def main_rq_snapshot(base_image, build):
	command = [
		"docker",
		"run",
		"--rm",
		"--read-only",
		"--network",
		NETWORK,
		"--tmpfs",
		"/tmp",
		"--mount",
		"type=volume,source=" + SITES_VOLUME + ",target=" + BENCH + "/sites,readonly",
		"--mount",
		"type=bind,source="
		+ str(Path(build).resolve() / "deploy/production")
		+ ",target=/release-tools,readonly",
		"--entrypoint",
		BENCH + "/env/bin/python",
		base_image,
		"/release-tools/joint_release_guards.py",
		"--rq-main-snapshot",
	]
	return json.loads(host_call(command))


def wait_main_drain(base_image, build, *, timeout=360):
	original = main_rq_snapshot(base_image, build)
	start = time.monotonic()
	while True:
		current = main_rq_snapshot(base_image, build)
		assert current["historical_orphans"] == original["historical_orphans"], (
			"Historical finished orphan changed; HOLD"
		)
		try:
			return {"rq": current, "scope": assert_main_rq_empty(current)}
		except AssertionError as error:
			if "Unknown" in str(error) or time.monotonic() - start >= timeout:
				raise
		time.sleep(1)


def sessions(user):
	return int(
		db_call(
			"SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER=" + sql_literal(user) + ";"
		).strip()
	)


def wait_sessions(user, *, timeout=120):
	start = time.monotonic()
	while sessions(user):
		assert time.monotonic() - start < timeout, "Original main sessions did not drain naturally; HOLD"
		time.sleep(1)


def runtime_access(root):
	"""Keep host-owned inputs private; only scoped runners join its sole-user group."""
	root = Path(root)
	uid, gid = os.getuid(), os.getgid()
	owner = pwd.getpwuid(uid)
	assert (
		gid != 0
		and {entry.pw_uid for entry in pwd.getpwall() if entry.pw_gid == gid} == {uid}
		and set(grp.getgrgid(gid).gr_mem) <= {owner.pw_name}
	), "Host primary group is not private; access refused"
	paths = [
		root,
		*root.glob("*.json"),
		*(root / name for name in ("main_site_lane.py", "joint_release_guards.py") if (root / name).exists()),
	]
	for path in paths:
		stats = path.lstat()
		assert (
			not path.is_symlink()
			and stats.st_uid == uid
			and stats.st_gid == gid
			and (path.is_dir() if path == root else path.is_file())
		), "Private runtime input is not host-owned or is a symlink; access refused"
	for path in paths:
		os.chmod(path, 0o750 if path == root else 0o640)
	return {"private_gid": gid, "host_uid": uid}


def private_roots(root, volume, config):
	assert volume["assets_link"] == BENCH + "/assets", "Unknown private asset root alias; HOLD"
	sites = root / "main-sites"
	for path in (sites, sites / SITE, sites / "logs"):
		path.mkdir(parents=True, exist_ok=True, mode=0o700)
		os.chmod(path, 0o2770 if path == sites / "logs" else 0o750)
	(sites / "assets").symlink_to(volume["assets_link"])
	common = json.loads(base64.b64decode(volume["common"]))
	for key in ("redis_queue", "redis_socketio"):
		common[key] = "redis://" + PROJECT + "-redis-queue-1:6379"
	common["redis_cache"] = "redis://" + PROJECT + "-redis-cache-1:6379"
	DDLReceipt(sites / "common_site_config.json", {})._write(serialized(common))
	DDLReceipt(sites / "apps.txt", {})._write(base64.b64decode(volume["apps"]))
	DDLReceipt(root / "main-site-config.json", {})._write(serialized(config))
	for path in (sites / "common_site_config.json", sites / "apps.txt", root / "main-site-config.json"):
		os.chmod(path, 0o640)


def preflight(root, build, base_image, image, candidate_sha):
	assert re.fullmatch(r"[0-9a-f]{40}", candidate_sha)
	private_gid = runtime_access(root)["private_gid"]
	originals = {service: inspect("frappe_docker-" + service + "-1") for service in RELEASE_SERVICES}
	assert_private_host_boundary(root, originals.values())
	baseline = {service: container_identity(value) for service, value in originals.items()}
	assert all(value["running"] and value["image"] == base_image for value in baseline.values()), (
		"Original six image/process identities drifted; HOLD"
	)
	backend = originals["backend"]
	mounts = [item for item in backend["Mounts"] if item["Destination"] == BENCH + "/sites"]
	assert (
		len(mounts) == 1
		and mounts[0]["Type"] == "volume"
		and mounts[0]["Name"] == SITES_VOLUME
		and backend["HostConfig"]["NetworkMode"] == NETWORK
	), "Unknown original main volume/network; HOLD"
	old_model = json.loads(
		host_call(
			[
				"docker",
				"compose",
				"-p",
				"frappe_docker",
				"-f",
				"compose.custom.yaml",
				"config",
				"--format",
				"json",
			]
		)
	)
	frontend = old_model["services"]["frontend"]
	assert frontend.get("command") == ["nginx-entrypoint.sh"] and any(
		port["target"] == 8080 and str(port["published"]) == "8888" for port in frontend["ports"]
	), "Unreviewed shared frontend command/port; HOLD"
	nginx = host_call(["docker", "exec", "frappe_docker-frontend-1", "nginx", "-T"])
	assert (
		"/etc/nginx/conf.d/" in nginx
		and "listen 8080" in nginx
		and "server_name deeplinkerp.com" not in nginx
	), "Unknown/conflicting exact main Nginx server; HOLD"
	host_call(["docker", "exec", "frappe_docker-frontend-1", "test", "!", "-e", ROUTE_TARGET])
	images = [
		json.loads(host_call(["docker", "image", "inspect", value]))[0] for value in (base_image, image)
	]
	assert (
		images[0]["Id"] == base_image
		and images[1]["Id"] == image
		and images[1]["RootFS"]["Layers"][: len(images[0]["RootFS"]["Layers"])]
		== images[0]["RootFS"]["Layers"]
	), "Candidate does not share approved base layers; HOLD"
	for key in ("Cmd", "Entrypoint"):
		assert images[0]["Config"][key] == images[1]["Config"][key], "Candidate native startup differs; HOLD"
	startup = images[0]["Config"]["Cmd"]
	assert isinstance(startup, list) and len(startup) == 1 and Path(startup[0]).name == "start.sh", (
		"Unknown native web startup; HOLD"
	)
	proofs = [image_call(value, build, "assets", assets_only=True) for value in (base_image, image)]
	assert proofs[0] == proofs[1], "Compiled shared asset/symlink/manifest image resolution differs; HOLD"
	starts = [
		image_call(value, build, "startup", payload={"command": startup[0]}, assets_only=True)
		for value in (base_image, image)
	]
	assert starts[0] == starts[1], "Native start.sh bytes differ; HOLD"
	volume = image_call(
		base_image,
		build,
		"volume",
		payload={"action": "snapshot", "subpath": ".deeplinkerp-main-lane/" + root.name + "/" + SITE},
	)
	configs = {site: json.loads(base64.b64decode(raw)) for site, raw in volume["configs"].items()}
	config = configs[SITE]
	old_user = config.get("db_user") or config["db_name"]
	assert all(
		(value.get("db_user") or value["db_name"]) != old_user
		for site, value in configs.items()
		if site != SITE
	), "Original main principal is shared; HOLD"
	accounts = account_snapshot(old_user)
	validate_accounts(accounts, old_user, config["db_name"])
	for table in ("tables_priv", "columns_priv", "procs_priv", "roles_mapping", "proxies_priv"):
		assert (
			int(
				db_call(
					"SELECT COUNT(*) FROM mysql.`" + table + "` WHERE User=" + sql_literal(old_user) + ";"
				).strip()
			)
			== 0
		), "Additional original main authority; HOLD"
	assert (
		db_call(
			"SELECT value FROM `"
			+ config["db_name"]
			+ "`.`tabSingles` WHERE doctype='System Settings' AND field='enable_scheduler';"
		).strip()
		== "0"
	), "Main global scheduler drifted; HOLD"
	redis = [inspect("frappe_docker-redis-" + name + "-1") for name in ("queue", "cache")]
	assert (
		all(value["State"]["Running"] and value["Config"]["Image"] == "redis:8.6-alpine" for value in redis)
		and redis[0]["Image"] == redis[1]["Image"]
	), "Unknown native Redis image/process; HOLD"
	new_user = "dlp_main_" + candidate_sha[:12] + "_" + secrets.token_hex(4)
	assert not account_snapshot(new_user), "New main principal already exists; HOLD"
	private_config = {
		**config,
		"db_user": new_user,
		"db_password": secrets.token_urlsafe(32),
		"maintenance_mode": 1,
	}
	for key in ("redis_queue", "redis_socketio", "redis_cache"):
		private_config.pop(key, None)
	model = lane_compose(
		image,
		redis[0]["Image"],
		str(root),
		".deeplinkerp-main-lane/" + root.name + "/" + SITE,
		private_gid=private_gid,
	)
	running_names = host_call(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines()
	assert not any(value["container_name"] in running_names for value in model["services"].values()), (
		"Existing/unknown main lane containers; HOLD"
	)
	assert (
		"deeplinkerp_main_rq"
		not in host_call(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines()
	), "Existing/unknown dedicated main RQ volume; HOLD"
	memory = sum(value["mem_limit"] for value in model["services"].values())
	available = (
		int(
			next(
				row.split()[1]
				for row in Path("/proc/meminfo").read_text().splitlines()
				if row.startswith("MemAvailable:")
			)
		)
		* 1024
	)
	assert available >= memory + 1024**3, "Insufficient actual RAM for bounded main processes; HOLD"
	budget = json.loads((root / "space-budget.json").read_bytes())
	assert 0 < images[1]["Size"] - images[0]["Size"] <= budget["overlay_limit_bytes"], (
		"Actual candidate overlay exceeds measured budget; HOLD"
	)
	compose_path = Path.cwd() / "compose.custom.yaml"
	route = Path.cwd() / "private/main-routes/deeplinkerp-main.conf"
	source = compose_path.read_bytes()
	frontend_bind(source, str(route) + ":" + ROUTE_TARGET + ":ro")
	assert not route.exists()
	contract = {
		"base_image": base_image,
		"image_id": image,
		"redis_image_id": redis[0]["Image"],
		"old_user": old_user,
		"new_user": new_user,
		"database": config["db_name"],
		"original_hosts": [value["host"] for value in accounts],
		"subpath": model["services"]["main-backend"]["volumes"][1]["volume"]["subpath"],
		"route_path": str(route),
		"compose_path": str(compose_path),
		"candidate_sha": candidate_sha,
		"private_gid": private_gid,
	}
	before = {
		"volume": volume,
		"accounts": accounts,
		"containers": baseline,
		"compose": base64.b64encode(source).decode(),
		"private_config": private_config,
		"assets": proofs[0],
		"startup": starts[0],
		"memory_available_bytes": available,
		"memory_limit_bytes": memory,
		"source_host": source_host_proof(),
	}
	return before, contract, model


def prepare(root, build, base_image, image, candidate_sha):
	root = Path(root).resolve()
	before, contract, model = preflight(root, build, base_image, image, candidate_sha)
	receipt = DDLReceipt.create(
		root / "main-seal.json",
		{"candidate_sha": candidate_sha, "contract_sha256": hashlib.sha256(serialized(contract)).hexdigest()},
		before,
		contract,
	)
	private_roots(root, before["volume"], before["private_config"])
	DDLReceipt(root / "main.compose.json", {})._write(serialized(model))
	compose(root, "config", "--quiet")
	install_route(receipt, maintenance=True, first=True)
	wait_main_maintenance()
	receipt.plan("physical-maintenance", {"maintenance": False}, {"maintenance": True}, kind="namespace")
	volume_call(receipt, build, "maintenance")
	receipt.complete("physical-maintenance", {"maintenance": True})
	drained = wait_main_drain(base_image, build)
	receipt.plan(
		"new-main-principal",
		{"exists": False},
		{"exists": True, "database": contract["database"]},
		kind="authentication",
	)
	database = contract["database"].replace("_", "\\_")
	db_call(
		"CREATE USER "
		+ sql_literal(contract["new_user"])
		+ "@'%' IDENTIFIED BY "
		+ sql_literal(before["private_config"]["db_password"])
		+ "; GRANT ALL PRIVILEGES ON `"
		+ database
		+ "`.* TO "
		+ sql_literal(contract["new_user"])
		+ "@'%';"
	)
	validate_accounts(account_snapshot(contract["new_user"]), contract["new_user"], contract["database"])
	receipt.complete("new-main-principal", {"exists": True, "database": contract["database"]})
	lock_accounts(receipt, before["accounts"])
	wait_sessions(contract["old_user"])
	drained_after = wait_main_drain(base_image, build)
	assert drained["rq"]["historical_orphans"] == drained_after["rq"]["historical_orphans"], (
		"Historical orphan changed during authentication seal; HOLD"
	)
	receipt.plan(
		"same-volume-main-rename",
		{"location": SITE},
		{"location": contract["subpath"]},
		kind="namespace",
		directory_identity=before["volume"]["directory_identity"],
	)
	moved = volume_call(receipt, build, "relocate")
	assert moved["location"] == contract["subpath"] and SITE not in moved["discovered_sites"]
	receipt.complete("same-volume-main-rename", {"location": contract["subpath"]})
	compose(root, "up", "-d", "--no-deps", "redis-queue", "redis-cache")
	compose(
		root, "up", "--no-start", "--no-deps", "backend", "frontend", "websocket", "queue-long", "queue-short"
	)
	receipt.finish(
		{
			"namespace": moved,
			"rq": drained_after,
			"private_config_sha256": hashlib.sha256(
				(root / "main-site-config.json").read_bytes()
			).hexdigest(),
			"staged_producers": [name for name in model["services"] if not name.startswith("main-redis-")],
		}
	)
	seal_proof(root, build)
	return {"main_sealed": True, "historical_shared_hold": drained_after["scope"]["shared_strict_hold"]}


def seal_proof(root, build):
	root = Path(root).resolve()
	receipt = DDLReceipt.load(root / "main-seal.json")
	contract = receipt.state["contract"]
	accounts = account_snapshot(contract["old_user"])
	assert {value["host"] for value in accounts} == set(contract["original_hosts"]) and all(
		value["priv"].get("account_locked") is True for value in accounts
	), "All original main Hosts must remain locked; HOLD"
	for old in receipt.state["before"]["accounts"]:
		actual = next(value for value in accounts if value["host"] == old["host"])
		assert actual["priv"] == {**old["priv"], "account_locked": True}, (
			"Original main authentication drift; HOLD"
		)
	assert sessions(contract["old_user"]) == 0, "Old main sessions remain; HOLD"
	namespace = volume_call(receipt, build, "proof")
	assert namespace["location"] == contract["subpath"] and namespace["maintenance_mode"] == 1
	model = frozen_model(root, receipt)
	for name, value in model["services"].items():
		current = inspect(value["container_name"])
		assert current["Image"] == value["image"] and current["State"]["Running"] == name.startswith(
			"main-redis-"
		), "Main producer staged identity changed; HOLD"
	config = json.loads((root / "main-site-config.json").read_bytes())
	assert (
		config == receipt.state["before"]["private_config"]
		and str(root / "main-site-config.json") not in contract["subpath"]
	), "Private credential bind changed; HOLD"
	assert_original_processes(
		receipt.state["before"]["containers"], "Original three-site processes changed; HOLD"
	)
	source_host_proof()
	rq = main_rq_snapshot(contract["base_image"], build)
	assert_main_rq_empty(rq)
	assert rq["historical_orphans"] == receipt.state["after"]["rq"]["rq"]["historical_orphans"], (
		"Historical orphan changed; HOLD"
	)
	proof = {
		"candidate_sha": contract["candidate_sha"],
		"observed_at": time.time(),
		"old_hosts": [value["host"] for value in accounts],
		"old_accounts_locked": True,
		"old_sessions": 0,
		"discovered_sites": namespace["discovered_sites"],
		"private_config": True,
		"source_idle": True,
		"old_containers_unchanged": True,
		"producer_containers_stopped": True,
		"new_user": contract["new_user"],
		"database": contract["database"],
	}
	validate_main_seal(receipt.state, proof, contract["candidate_sha"])
	DDLReceipt(root / "main-seal-proof.json", {})._write(serialized(proof))
	return proof


def private_maintenance(receipt, root, *, enable):
	path = Path(root) / "main-site-config.json"
	raw = path.read_bytes()
	config = json.loads(raw)
	value = {**config, "maintenance_mode": int(enable)}
	content = serialized(value)
	if config == value:
		return
	step = "private-maintenance-on" if enable else "private-maintenance-off"
	before = {"sha256": hashlib.sha256(raw).hexdigest()}
	after = {"sha256": hashlib.sha256(content).hexdigest()}
	receipt.plan(step, before, after, kind="configuration")
	# File bind mounts pin an inode. This host-private file is updated in place
	# only while main is held behind the all-URL route; fsync precedes startup.
	fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
	with os.fdopen(fd, "wb") as output:
		output.write(content)
		output.flush()
		os.fsync(output.fileno())
	assert path.read_bytes() == content
	receipt.complete(step, after)


def receipt_budget(root, build):
	root = Path(root).resolve()
	receipt = DDLReceipt.load(root / "main-seal.json")
	budget = json.loads((root / "space-budget.json").read_bytes())
	paths = list(root.rglob("*"))
	assert all(
		not path.is_symlink()
		or (path == root / "main-sites/assets" and os.readlink(path) == BENCH + "/assets")
		for path in paths
	), "Unknown private receipt storage/alias; HOLD"
	host_bytes = sum(path.stat().st_size for path in paths if not path.is_symlink() and path.is_file())
	native = image_call(
		receipt.state["contract"]["base_image"],
		build,
		"evidence-budget",
		payload={
			"subpath": receipt.state["contract"]["subpath"],
			"candidate_sha": receipt.state["identity"]["candidate_sha"],
		},
	)
	total = host_bytes + native["native_receipt_bytes"]
	assert 0 < total <= budget["receipt_limit_bytes"], (
		"Actual metadata/audit receipts exceed reserved budget; HOLD"
	)
	return {"observed_receipt_bytes": total, "reserved_receipt_bytes": budget["receipt_limit_bytes"]}


def resume(root, build):
	root = Path(root).resolve()
	receipt = DDLReceipt.load(root / "main-seal.json")
	seal_proof(root, build)
	marker = image_call(
		receipt.state["contract"]["base_image"],
		build,
		"resume-check",
		payload={
			"subpath": receipt.state["contract"]["subpath"],
			"candidate_sha": receipt.state["identity"]["candidate_sha"],
			"image_id": receipt.state["contract"]["image_id"],
		},
	)
	assert marker["first_resume"] == "main-candidate-serving", (
		"Durable main first-producer intent missing; HOLD"
	)
	private_maintenance(receipt, root, enable=False)
	compose(root, "up", "-d", "--no-deps", "backend", "frontend", "websocket", "queue-long", "queue-short")
	model = frozen_model(root, receipt)
	for value in model["services"].values():
		current = inspect(value["container_name"])
		assert (
			current["Image"] == value["image"]
			and current["State"]["Running"]
			and not current["State"].get("OOMKilled")
		), "Main candidate startup unconfirmed; forward HOLD"
	install_route(receipt, maintenance=False)
	start = time.monotonic()
	while True:
		status = host_call(
			[
				"curl",
				"-sS",
				"--max-time",
				"10",
				"-o",
				"/dev/null",
				"-w",
				"%{http_code}",
				"-H",
				"Host: " + SITE,
				"http://127.0.0.1:8888/api/method/ping",
			]
		)
		if status == "200":
			break
		assert time.monotonic() - start < 90, "Main routed health timeout; forward HOLD"
		time.sleep(1)
	assert_original_processes(
		receipt.state["before"]["containers"], "Original three-site processes changed; forward HOLD"
	)
	for site in SHARED_SITES[1:]:
		host_call(["curl", "-fsS", "--max-time", "10", "https://" + site + "/api/method/ping"])
	return {"main_candidate_running": True, "online_browser_acceptance": "pending"}


def hold(root):
	root = Path(root).resolve()
	receipt = DDLReceipt.load(root / "main-seal.json")
	failures = []
	for name, action in (
		("route", lambda: install_route(receipt, maintenance=True)),
		("private-maintenance", lambda: private_maintenance(receipt, root, enable=True)),
		("source-timer", lambda: host_call(["systemctl", "--user", "stop", "deeplinkerp-source-sync.timer"])),
	):
		try:
			action()
		except Exception:
			failures.append(name)
	DDLReceipt(root / "main-hold-attempt.json", {})._write(
		serialized(
			{
				"outcome": "HOLD",
				"confirmed": not failures,
				"failed_actions": failures,
				"forward_only_after_resume": True,
			}
		)
	)
	if failures:
		raise RuntimeError("Main HOLD unconfirmed: " + ", ".join(failures))
	return {"main_maintenance": True, "forward_only_after_resume": True}


def health(root, build):
	root = Path(root).resolve()
	receipt = DDLReceipt.load(root / "main-seal.json")
	model = frozen_model(root, receipt)
	contract, before = receipt.state["contract"], receipt.state["before"]
	assert receipt.state["status"] == "applied" and json.loads(
		(root / "main-site-config.json").read_bytes()
	) == {**before["private_config"], "maintenance_mode": 0}, (
		"Main private configuration differs; forward HOLD"
	)
	route = Path(contract["route_path"])
	assert route.read_text() == main_route(maintenance=False) and Path(
		contract["compose_path"]
	).read_bytes() == frontend_bind(
		base64.b64decode(before["compose"]), str(route) + ":" + ROUTE_TARGET + ":ro"
	), "Managed main route/bind differs; forward HOLD"
	assert host_call(["docker", "exec", "frappe_docker-frontend-1", "cat", ROUTE_TARGET]) == main_route(
		maintenance=False
	), "Installed main all-URL route differs; forward HOLD"
	metadata = DDLReceipt.load(root / "joint-receipt.json").state
	assert (
		metadata["identity"]["candidate_sha"] == contract["candidate_sha"] and metadata["status"] == "applied"
	), "Main bounded metadata receipt unconfirmed; forward HOLD"
	for value in model["services"].values():
		current = inspect(value["container_name"])
		assert (
			current["Image"] == value["image"]
			and current["State"]["Running"]
			and not current["State"].get("OOMKilled")
		), "Main running identity/health changed; forward HOLD"
	assert_original_processes(
		receipt.state["before"]["containers"], "Original three-site processes changed; forward HOLD"
	)
	namespace = volume_call(receipt, build, "proof")
	assert namespace["discovered_sites"] == sorted(SHARED_SITES[1:]) and namespace["maintenance_mode"] == 1
	accounts = account_snapshot(receipt.state["contract"]["old_user"])
	assert {value["host"] for value in accounts} == set(receipt.state["contract"]["original_hosts"]) and all(
		value["priv"].get("account_locked") is True for value in accounts
	)
	for old in before["accounts"]:
		assert next(value["priv"] for value in accounts if value["host"] == old["host"]) == {
			**old["priv"],
			"account_locked": True,
		}, "Original main authentication drift; forward HOLD"
	assert sessions(receipt.state["contract"]["old_user"]) == 0
	validate_accounts(
		account_snapshot(receipt.state["contract"]["new_user"]),
		receipt.state["contract"]["new_user"],
		receipt.state["contract"]["database"],
	)
	assert (
		db_call(
			"SELECT value FROM `"
			+ receipt.state["contract"]["database"]
			+ "`.`tabSingles` WHERE doctype='System Settings' AND field='enable_scheduler';"
		).strip()
		== "0"
	)
	for name in ("queue", "cache"):
		assert (
			host_call(["docker", "exec", PROJECT + "-redis-" + name + "-1", "redis-cli", "PING"]).strip()
			== "PONG"
		)
	persistence = host_call(
		["docker", "exec", PROJECT + "-redis-queue-1", "redis-cli", "INFO", "persistence"]
	)
	assert "aof_enabled:1" in persistence and "aof_last_write_status:ok" in persistence, (
		"Accepted main queue persistence unconfirmed; forward HOLD"
	)
	for site in SHARED_SITES:
		host_call(["curl", "-fsS", "--max-time", "10", "https://" + site + "/api/method/ping"])
	return {
		"main_running": True,
		"original_sites_running": list(SHARED_SITES[1:]),
		"scheduler_enabled": 0,
		"rq_aof": True,
	}


def restore(root, build):
	"""Only pre-runtime restore; schema restoration/full audit is the caller's job."""
	root = Path(root).resolve()
	receipt = DDLReceipt.load(root / "main-seal.json")
	contract, before = receipt.state["contract"], receipt.state["before"]
	image_call(
		contract["base_image"],
		build,
		"pre-resume",
		payload={"subpath": contract["subpath"], "candidate_sha": receipt.state["identity"]["candidate_sha"]},
	)
	compose_path, route = Path(contract["compose_path"]), Path(contract["route_path"])
	source = base64.b64decode(before["compose"])
	changed = frontend_bind(source, str(route) + ":" + ROUTE_TARGET + ":ro")
	attempted = any(step["id"] == "route-maintenance-first" for step in receipt.state["steps"])
	compose_actual = compose_path.read_bytes()
	assert (
		not compose_path.is_symlink()
		and not route.is_symlink()
		and compose_actual in ({source, changed} if attempted else {source})
	), "Dirty Compose changed outside the recorded attempt; HOLD"
	assert not route.exists() or (attempted and route.read_text() == main_route(maintenance=True)), (
		"Managed route changed outside the recorded attempt; HOLD"
	)
	route_changed = compose_actual != source or route.exists()
	# No runtime container may have run. A failed partial preparation does not
	# need to invent a completed seal receipt to restore its recorded boundary.
	names = host_call(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines()
	for name in ("backend", "frontend", "websocket", "queue-long", "queue-short"):
		container = PROJECT + "-" + name + "-1"
		if container in names:
			assert not inspect(container)["State"]["Running"], "Candidate producer resumed; forward HOLD"
	assert_original_processes(
		before["containers"], "Original processes drifted; HOLD", allow_legacy_mount_order=True
	)
	new_accounts = account_snapshot(contract["new_user"])
	if new_accounts:
		assert len(new_accounts) == 1 and new_accounts[0]["host"] == "%", "Unknown new principal scope; HOLD"
		receipt.plan("seal-new-before-restore", {"present": True}, {"present": False}, kind="authentication")
		db_call("ALTER USER " + sql_literal(contract["new_user"]) + "@'%' ACCOUNT LOCK;")
		wait_sessions(contract["new_user"])
		db_call("DROP USER " + sql_literal(contract["new_user"]) + "@'%';")
		assert not account_snapshot(contract["new_user"])
		receipt.complete("seal-new-before-restore", {"present": False})
	# A partial seal may not have locked every account. Persist old-producer
	# intent before restoring maintenance/discovery, as well as before UNLOCK.
	image_call(
		contract["base_image"],
		build,
		"old-resume",
		payload={
			"subpath": contract["subpath"],
			"candidate_sha": receipt.state["identity"]["candidate_sha"],
			"image_id": contract["base_image"],
		},
		writable=True,
	)
	receipt.plan("original-main-namespace", {"restored": False}, {"restored": True}, kind="namespace")
	volume_call(receipt, build, "restore")
	receipt.complete("original-main-namespace", {"restored": True})
	for original in before["accounts"]:
		step = "restore-old-auth-" + original["host"]
		receipt.plan(
			step,
			{"locked": True},
			{"original_priv_sha256": hashlib.sha256(serialized(original["priv"])).hexdigest()},
			kind="authentication",
		)
		# Restore exact original JSON, including absent lock key and auth hashes.
		raw = json.dumps(original["priv"], separators=(",", ":")).encode().hex()
		db_call(
			"UPDATE mysql.global_priv SET Priv=CONVERT(0x"
			+ raw
			+ " USING utf8mb4) WHERE User="
			+ sql_literal(original["user"])
			+ " AND Host="
			+ sql_literal(original["host"])
			+ ";"
		)
		actual = next(
			value for value in account_snapshot(original["user"]) if value["host"] == original["host"]
		)
		assert actual["priv"] == original["priv"], "Original authentication restore differs; forward HOLD"
		receipt.complete(
			step, {"original_priv_sha256": hashlib.sha256(serialized(original["priv"])).hexdigest()}
		)
	db_call("FLUSH PRIVILEGES;")
	assert account_snapshot(contract["old_user"]) == before["accounts"], (
		"Original auth/Host grants restore differs; forward HOLD"
	)
	if route_changed:
		assert compose_path.read_bytes() == compose_actual, (
			"Dirty Compose changed during restore; forward HOLD"
		)
		receipt.plan("route-original", {"managed": True}, {"managed": False}, kind="route")
		if compose_actual != source:
			mode = compose_path.stat().st_mode & 0o777
			DDLReceipt(compose_path, {})._write(source)
			os.chmod(compose_path, mode)
		if route.exists():
			host_call(["docker", "exec", "frappe_docker-frontend-1", "rm", "-f", "--", ROUTE_TARGET])
			route.unlink()
			DDLReceipt._sync_directory(route.parent)
			host_call(["docker", "exec", "frappe_docker-frontend-1", "nginx", "-t"])
			host_call(["docker", "exec", "frappe_docker-frontend-1", "nginx", "-s", "reload"])
		receipt.complete("route-original", {"managed": False})
	receipt.restored()
	return {"original_main_boundary_restored": True, "first_resume": "old-main-account-unlock"}


def main():
	import argparse

	argv = sys.argv[1:]
	extra = []
	if "--" in argv:
		index = argv.index("--")
		extra = argv[index + 1 :]
		argv = argv[:index]
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"action",
		choices=(
			"prepare",
			"run",
			"resume",
			"hold",
			"restore",
			"proof",
			"health",
			"space",
			"boundary-pre-resume",
			"volume",
			"assets",
			"startup",
			"resume-check",
			"pre-resume",
			"old-resume",
			"evidence-budget",
			"runtime-access",
		),
	)
	parser.add_argument("--evidence", type=Path)
	parser.add_argument("--build", type=Path)
	parser.add_argument("--base-image")
	parser.add_argument("--image-id")
	parser.add_argument("--candidate-sha")
	parser.add_argument("--entrypoint")
	args = parser.parse_args(argv)
	try:
		if args.action in {
			"volume",
			"startup",
			"resume-check",
			"pre-resume",
			"old-resume",
			"evidence-budget",
		}:
			payload = json.load(sys.stdin)
		if args.action == "volume":
			result = site_boundary(
				BENCH + "/sites", payload["action"], payload["subpath"], payload.get("original")
			)
		elif args.action == "assets":
			result = asset_view(BENCH)
		elif args.action == "startup":
			import shutil

			path = Path(shutil.which(payload["command"]) or payload["command"])
			content = path.read_text()
			assert (
				"gunicorn" in content
				and "frappe.app:application" in content
				and "exec " in content
				and not any(
					word in content for word in ("migrate", "new-site", "bench build", "bench schedule")
				)
			), "Unknown native start.sh behavior; HOLD"
			result = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
		elif args.action in {"resume-check", "pre-resume", "old-resume", "evidence-budget"}:
			from joint_release_guards import assert_pre_resume, record_resume

			root = Path(BENCH) / "sites"
			site = root / payload["subpath"] if (root / payload["subpath"]).exists() else root / SITE
			path = (
				site
				/ "private/release-evidence"
				/ ("joint-" + payload["candidate_sha"][:12] + ".resume.json")
			)
			if args.action == "evidence-budget":
				paths = [path, path.with_name(path.name.replace(".resume.json", ".json"))]
				assert all(not value.is_symlink() for value in paths), "Unknown native receipt location; HOLD"
				result = {
					"native_receipt_bytes": sum(value.stat().st_size for value in paths if value.is_file())
				}
			elif args.action == "pre-resume":
				if path.parent.exists():
					assert_pre_resume(path)
				else:
					assert (
						site.is_dir()
						and not site.is_symlink()
						and (site / "private").is_dir()
						and not (site / "private").is_symlink()
					), "Unknown pre-resume site/evidence location; HOLD"
				result = {"pre_resume": True}
			elif args.action == "old-resume":
				path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
				result = record_resume(
					path,
					{"candidate_sha": payload["candidate_sha"], "image_id": payload["image_id"]},
					"old-main-account-unlock",
				)["contract"]
			else:
				state = DDLReceipt.load(path).state
				assert (
					state["identity"]["candidate_sha"] == payload["candidate_sha"]
					and state["contract"]["image_id"] == payload["image_id"]
				)
				result = state["contract"]
		elif args.action == "runtime-access":
			result = runtime_access(args.evidence)
		elif args.action == "prepare":
			result = prepare(args.evidence, args.build, args.base_image, args.image_id, args.candidate_sha)
		elif args.action == "proof":
			result = seal_proof(args.evidence, args.build)
		elif args.action == "resume":
			result = resume(args.evidence, args.build)
		elif args.action == "hold":
			result = hold(args.evidence)
		elif args.action == "restore":
			result = restore(args.evidence, args.build)
		elif args.action == "health":
			result = health(args.evidence, args.build)
		elif args.action == "space":
			result = receipt_budget(args.evidence, args.build)
		elif args.action == "boundary-pre-resume":
			receipt = DDLReceipt.load(args.evidence / "main-seal.json")
			result = image_call(
				receipt.state["contract"]["base_image"],
				args.build,
				"pre-resume",
				payload={
					"subpath": receipt.state["contract"]["subpath"],
					"candidate_sha": receipt.state["identity"]["candidate_sha"],
				},
			)
		else:
			seal_proof(args.evidence, args.build)
			assert args.entrypoint in {BENCH + "/env/bin/python", "bench"}, (
				"Unknown bounded main release entrypoint"
			)
			if args.entrypoint == "bench":
				assert extra == ["--site", SITE, "clear-cache"], "Only main cache clear is allowed"
			command = runner_command(
				args.evidence, args.build, args.image_id, args.entrypoint, extra, args.candidate_sha
			)
			completed = subprocess.run(command, check=False)
			return completed.returncode
		print(json.dumps(result, sort_keys=True))
		return 0
	except Exception as error:
		failure = {
			"outcome": "HOLD",
			"reason": "Main isolation action unconfirmed; inspect the private durable receipt",
			"phase": args.action,
			"exception_type": type(error).__name__,
			"locations": [
				{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
				for frame in traceback.extract_tb(error.__traceback__)
				if Path(frame.filename).name in {"main_site_lane.py", "joint_release_guards.py"}
			],
		}
		changes = getattr(error, "original_process_changes", {})
		if isinstance(changes, dict):
			fields = {
				service: [field for field in CONTAINER_IDENTITY_FIELDS if field in names]
				for service, names in changes.items()
				if service in RELEASE_SERVICES
				and isinstance(names, list)
				and all(isinstance(name, str) for name in names)
			}
			if fields:
				failure["original_process_changes"] = fields
		if args.action == "runtime-access":
			failure.update(
				{
					"outcome": "PRIVATE_ACCESS_FAILED",
					"host_uid": os.getuid(),
					"private_gid": os.getgid(),
					"reason": "Private group, ownership or access is unconfirmed",
				}
			)
		root = args.evidence
		if root:
			name = (
				"private-access-failure.json"
				if args.action == "runtime-access"
				else "main-action-failure.json"
			)
			try:
				if root.is_dir() and not root.is_symlink() and root.stat().st_uid == os.getuid():
					DDLReceipt(root / name, {})._write(serialized(failure))
				else:
					failure["durable_log"] = "unconfirmed"
			except OSError:
				failure["durable_log"] = "unconfirmed"
		print(json.dumps(failure, sort_keys=True), file=sys.stderr)
		return 1


if __name__ == "__main__":
	sys.exit(main())
