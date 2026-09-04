import base64
import hashlib
import hmac
import json
import pickle
import secrets
from urllib.parse import urlencode

import frappe
import redis
import requests
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.www.login import sanitize_redirect
from frappe.utils.oauth import (
	get_oauth2_flow,
	get_oauth2_providers,
	get_redirect_uri,
	redirect_post_login,
)


EIMS_PROVIDER_CONFIG_KEY = "eims_social_login_key"
EIMS_PROVIDER_FALLBACK = "eims"
EIMS_USER_ID_FIELD = "custom_eims_app_user_id"
EIMS_HOME_PATH = "/desk"
EIMS_START_PATH = "/api/method/custom_filters.overrides.oauth.start_eims_login"
EIMS_STATE_PREFIX = "eims_oauth_state:"
EIMS_BROWSER_NONCE_COOKIE = "eims_oauth_nonce"
EIMS_STATE_TTL_SECONDS = 10 * 60
OAUTH_REQUEST_TIMEOUT = 15
SSO_START_RATE_LIMIT = 10
SSO_CALLBACK_RATE_LIMIT = 10
SSO_RATE_LIMIT_SECONDS = 60
_SENSITIVE_LOG_KEY_PARTS = ("password", "passwd", "secret", "token", "authorization")
_SENSITIVE_LOG_KEYS = {"code", "state", "code_verifier"}


class EIMSUserBindingError(Exception):
	"""The EIMS identity is valid but has no usable ERP user binding."""


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=SSO_START_RATE_LIMIT, seconds=SSO_RATE_LIMIT_SECONDS)
def start_eims_login(redirect_to: str | None = None):
	"""Create the server-side OAuth state/PKCE pair and start EIMS authorization."""
	provider = _get_eims_provider()
	oauth2_providers = get_oauth2_providers()
	provider_config = oauth2_providers.get(provider) or {}
	if not provider_config:
		frappe.throw(_("未找到配置的 EIMS Social Login Key：{0}").format(provider))
	flow = get_oauth2_flow(provider)
	if not provider_config.get("flow_params", {}).get("authorize_url"):
		frappe.throw(_("EIMS Social Login Key 未配置授权地址"))

	state = secrets.token_urlsafe(32)
	code_verifier = secrets.token_urlsafe(64)
	browser_nonce = secrets.token_urlsafe(32)
	state_digest = _state_digest(state)
	redirect_to = sanitize_redirect(redirect_to) if redirect_to else None

	frappe.cache.set_value(
		f"{EIMS_STATE_PREFIX}{state_digest}",
		{
			"state_digest": state_digest,
			"code_verifier": code_verifier,
			"browser_nonce_digest": _state_digest(browser_nonce),
			"redirect_to": redirect_to,
			"session_id": getattr(frappe.local.session, "sid", None),
		},
		expires_in_sec=EIMS_STATE_TTL_SECONDS,
	)
	frappe.local.cookie_manager.set_cookie(
		EIMS_BROWSER_NONCE_COOKIE,
		browser_nonce,
		max_age=EIMS_STATE_TTL_SECONDS,
		httponly=True,
		samesite="Lax",
	)

	auth_url_data = provider_config.get("auth_url_data", {}) or {}
	authorize_params = {
		"client_id": flow.client_id,
		"redirect_uri": get_redirect_uri(provider),
		"response_type": "code",
		"scope": auth_url_data.get("scope", "openid profile"),
		"state": state,
		"code_challenge": _code_challenge(code_verifier),
		"code_challenge_method": "S256",
	}

	# Keep optional provider parameters, but never allow stored settings to replace
	# security-sensitive values or accidentally expose the client secret.
	for key, value in auth_url_data.items():
		if key not in {
			"client_id",
			"client_secret",
			"redirect_uri",
			"response_type",
			"state",
			"code_challenge",
			"code_challenge_method",
			"scope",
		}:
			authorize_params[key] = value

	authorize_url = flow.get_authorize_url(**authorize_params)
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = authorize_url


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=SSO_CALLBACK_RATE_LIMIT, seconds=SSO_RATE_LIMIT_SECONDS)
def login_via_eims(code: str, state: str):
	try:
		if not isinstance(code, str) or not code.strip():
			frappe.throw(_("EIMS OAuth 回调缺少授权码"))

		# A login page rendered before PKCE was enabled can still have the old
		# Frappe OAuth URL in the browser. Its state has no server-side verifier.
		# Discard that authorization code and restart the flow instead of ever
		# exchanging a code without PKCE validation.
		legacy_state = _decode_legacy_frappe_state(state)
		if legacy_state:
			redirect_to = legacy_state.get("redirect_to")
			redirect_to = sanitize_redirect(redirect_to) if redirect_to else None
			frappe.local.response["type"] = "redirect"
			frappe.local.response["location"] = _build_start_url(redirect_to)
			return

		state_data = _consume_state(state)
		provider = _get_eims_provider()
		oauth2_providers = get_oauth2_providers()
		provider_config = oauth2_providers.get(provider) or {}
		if not provider_config:
			frappe.throw(_("未找到配置的 EIMS Social Login Key：{0}").format(provider))
		flow = get_oauth2_flow(provider)
		api_endpoint = provider_config.get("api_endpoint")
		if not api_endpoint:
			frappe.throw(_("EIMS Social Login Key 未配置 UserInfo 地址"))

		# EIMS 支持 client_secret_post。client_secret 从 Social Login Key
		# 服务端解密读取，永远不会进入授权跳转 URL 或前端页面。
		token_response = requests.post(
			flow.access_token_url,
			data={
				"code": code.strip(),
				"redirect_uri": get_redirect_uri(provider),
				"grant_type": "authorization_code",
				"client_id": flow.client_id,
				"client_secret": flow.client_secret,
				"code_verifier": state_data["code_verifier"],
			},
			headers={"Accept": "application/json"},
			timeout=OAUTH_REQUEST_TIMEOUT,
		)
		token_data = _parse_json_response(token_response, "Token")

		access_token = token_data.get("access_token")
		if token_response.status_code >= 400 or not access_token:
			error_message = _get_error_message(token_data)
			raise RuntimeError(
				f"EIMS Token 请求失败（HTTP {token_response.status_code}）：{error_message}"
			)

		# EIMS userinfo 返回 app_user_id 时，才有资格映射到 ERP 用户。
		userinfo_response = requests.get(
			api_endpoint,
			headers={
				"Accept": "application/json",
				"Authorization": f"Bearer {access_token}",
			},
			timeout=OAUTH_REQUEST_TIMEOUT,
		)
		info = _parse_json_response(userinfo_response, "UserInfo")

		if userinfo_response.status_code >= 400:
			error_message = _get_error_message(info)
			raise RuntimeError(
				f"EIMS UserInfo 请求失败（HTTP {userinfo_response.status_code}）：{error_message}"
			)

		# 兼容部分接口将用户信息放在 data 对象中返回的情况。
		if isinstance(info.get("data"), dict) and not info.get("sub"):
			info = info["data"]

		app_user_id = _normalize_app_user_id(info.get("app_user_id"))
		user = _get_user_by_eims_app_user_id(app_user_id)

		# 只有已启用且已绑定的 ERP 用户可以通过 EIMS 登录。
		frappe.local.login_manager.login_as(user.name)
		frappe.db.commit()

		redirect_post_login(
			desk_user=user.user_type == "System User",
			redirect_to=state_data.get("redirect_to"),
			provider=provider,
		)

	except EIMSUserBindingError as e:
		frappe.log_error(f"EIMS SSO user binding failed: {e}", "EIMS OAuth SSO")
		frappe.respond_as_web_page(
			_("ERP 未绑定 EIMS 账号"),
			_("当前 EIMS 账号未在 ERP 中绑定对应用户，请联系管理员配置 EIMS App User ID 后重试。"),
			http_status_code=403,
			primary_action="/login",
			primary_label=_("返回登录页"),
			fullpage=True,
		)
		return

	except Exception as e:
		frappe.log_error(f"EIMS SSO login failed: {e}", "EIMS OAuth SSO")
		frappe.respond_as_web_page(
			_("EIMS 登录失败"),
			_("EIMS 登录未完成，请返回登录页重试；如问题持续请联系管理员。"),
			http_status_code=417,
			primary_action="/login",
			primary_label=_("返回登录页"),
			fullpage=True,
		)
		return


def _decode_legacy_frappe_state(state):
	"""Return the old Frappe OAuth state, if this is a stale login-page flow."""
	if not isinstance(state, str):
		return None

	try:
		padding = "=" * (-len(state) % 4)
		payload = json.loads(base64.urlsafe_b64decode(state + padding).decode("utf-8"))
	except (TypeError, ValueError, UnicodeError):
		return None

	if not isinstance(payload, dict):
		return None
	if not isinstance(payload.get("site"), str) or not payload.get("token"):
		return None

	configured_site = frappe.utils.get_url().rstrip("/")
	if payload["site"].rstrip("/") != configured_site:
		return None

	return payload


def update_website_context(context):
	"""Make Frappe's EIMS login button enter our backend start endpoint."""
	request_path = getattr(frappe.local.request, "path", "").rstrip("/")
	if request_path != "/login":
		return

	provider_name = _get_eims_provider()
	redirect_to = frappe.local.request.args.get("redirect-to")
	for provider in context.get("provider_logins", []):
		if provider.get("name") == provider_name:
			provider["auth_url"] = _build_start_url(redirect_to)


def scrub_sensitive_oauth_request_log(response=None, request=None):
	"""Redact OAuth credentials before Frappe adds form data to request logs."""
	form_dict = getattr(frappe.local, "form_dict", None)
	if not isinstance(form_dict, dict):
		return

	for key in list(form_dict):
		value = form_dict[key]
		if _is_sensitive_log_key(key):
			form_dict[key] = "[REDACTED]"
			continue

		if isinstance(value, str):
			try:
				value = json.loads(value)
			except (TypeError, ValueError):
				continue
			form_dict[key] = _redact_log_payload(value)
		elif isinstance(value, (dict, list)):
			form_dict[key] = _redact_log_payload(value)


def _is_sensitive_log_key(key) -> bool:
	normalized_key = str(key).lower()
	return normalized_key in _SENSITIVE_LOG_KEYS or any(
		part in normalized_key for part in _SENSITIVE_LOG_KEY_PARTS
	)


def _redact_log_payload(value):
	if isinstance(value, dict):
		return {
			key: "[REDACTED]" if _is_sensitive_log_key(key) else _redact_log_payload(item)
			for key, item in value.items()
		}
	if isinstance(value, list):
		return [_redact_log_payload(item) for item in value]
	return value


def redirect_guest_home_to_eims(path: str):
	"""Start SSO when an unauthenticated user opens the ERP home page."""
	from frappe.website.path_resolver import resolve_path

	provider = _get_eims_provider()
	if (
		path in ("", "app", "desk")
		and frappe.session.user == "Guest"
		and frappe.db.get_value("Social Login Key", provider, "enable_social_login")
	):
		frappe.flags.redirect_location = _build_start_url(EIMS_HOME_PATH)
		raise frappe.Redirect(302)

	return resolve_path(path)


def _get_eims_provider() -> str:
	"""Return the configured Social Login Key document name for EIMS."""
	provider = frappe.conf.get(EIMS_PROVIDER_CONFIG_KEY)
	if isinstance(provider, str) and provider.strip():
		return provider.strip()
	return EIMS_PROVIDER_FALLBACK


def _build_start_url(redirect_to: str | None = None) -> str:
	url = EIMS_START_PATH
	if redirect_to:
		url += "?" + urlencode({"redirect_to": redirect_to})
	return url


def _consume_state(state: str) -> dict:
	"""Read and immediately consume the one-time server-side OAuth state."""
	if not isinstance(state, str) or not state:
		raise RuntimeError("EIMS OAuth 回调缺少 state 参数")

	state_digest = _state_digest(state)
	cache_key = f"{EIMS_STATE_PREFIX}{state_digest}"
	state_data = _get_and_delete_cache_value(cache_key)

	if not isinstance(state_data, dict):
		raise RuntimeError("EIMS OAuth state 已失效或未找到")

	stored_digest = state_data.get("state_digest")
	if not isinstance(stored_digest, str) or not hmac.compare_digest(state_digest, stored_digest):
		raise RuntimeError("EIMS OAuth state 校验失败")

	stored_session_id = state_data.get("session_id")
	current_session_id = getattr(frappe.local.session, "sid", None)
	if stored_session_id and (
		not current_session_id
		or not hmac.compare_digest(str(stored_session_id), str(current_session_id))
	):
		raise RuntimeError("EIMS OAuth state 与当前会话不匹配")

	stored_browser_nonce_digest = state_data.get("browser_nonce_digest")
	browser_nonce = _get_request_cookie(EIMS_BROWSER_NONCE_COOKIE)
	if (
		not isinstance(stored_browser_nonce_digest, str)
		or not browser_nonce
		or not hmac.compare_digest(_state_digest(browser_nonce), stored_browser_nonce_digest)
	):
		raise RuntimeError("EIMS OAuth state 与当前浏览器不匹配")

	if not state_data.get("code_verifier"):
		raise RuntimeError("EIMS OAuth state 缺少 PKCE verifier")

	frappe.local.cookie_manager.delete_cookie(EIMS_BROWSER_NONCE_COOKIE)
	redirect_to = state_data.get("redirect_to")
	state_data["redirect_to"] = sanitize_redirect(redirect_to) if redirect_to else None
	return state_data


def _get_request_cookie(name: str) -> str | None:
	request = getattr(frappe.local, "request", None)
	cookies = getattr(request, "cookies", None)
	value = cookies.get(name) if cookies else None
	return value if isinstance(value, str) and value else None


def _get_and_delete_cache_value(cache_key: str):
	"""Consume a cache value atomically when Redis supports GETDEL."""
	cache = frappe.cache
	redis_key = cache.make_key(cache_key)

	# Frappe keeps a request-local cache in addition to Redis. Remove a possible
	# stale copy before reading the shared value directly.
	local_cache = getattr(frappe.local, "cache", None)
	if local_cache is not None:
		local_cache.pop(redis_key, None)

	try:
		raw_value = cache.getdel(redis_key)
	except (AttributeError, redis.exceptions.ResponseError):
		# Compatibility for cache implementations without Redis GETDEL. This path
		# is not atomic, but still preserves the previous behavior on old Redis.
		state_data = cache.get_value(cache_key, use_local_cache=False)
		cache.delete_value(cache_key)
		return state_data

	if raw_value is None:
		return None
	if isinstance(raw_value, dict):
		return raw_value
	if not isinstance(raw_value, bytes | bytearray):
		return None

	try:
		return pickle.loads(raw_value)
	except (EOFError, pickle.UnpicklingError, TypeError):
		return None


def _state_digest(state: str) -> str:
	key = str(frappe.conf.get("encryption_key") or "").encode("utf-8")
	return hmac.new(key, state.encode("utf-8"), hashlib.sha256).hexdigest()


def _code_challenge(code_verifier: str) -> str:
	digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
	return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _parse_json_response(response, endpoint: str) -> dict:
	try:
		data = response.json()
	except ValueError as e:
		raise RuntimeError(f"EIMS {endpoint} 返回了非 JSON 响应（HTTP {response.status_code}）") from e

	if not isinstance(data, dict):
		raise RuntimeError(f"EIMS {endpoint} 返回的 JSON 格式无效")
	return data


def _get_error_message(data: dict):
	for key in ("msg", "error_description", "error", "message"):
		value = data.get(key)
		if value is not None:
			return _safe_log_text(value)
	return "EIMS provider returned an unspecified error"


def _safe_log_text(value, max_length: int = 300) -> str:
	"""Keep provider-controlled log messages short and free of line breaks."""
	text = str(value).replace("\r", " ").replace("\n", " ").strip()
	return text[:max_length]


def _normalize_app_user_id(value) -> str:
	"""Normalize EIMS identity values without coercing string IDs to integers."""
	if isinstance(value, bool) or value is None:
		raise RuntimeError("EIMS userinfo 未返回有效的 app_user_id")

	if isinstance(value, str):
		app_user_id = value.strip()
	elif isinstance(value, int):
		# Some EIMS responses still return numeric JSON values. Keep the lookup
		# field's string semantics while remaining compatible with those responses.
		app_user_id = str(value)
	else:
		raise RuntimeError("EIMS userinfo 返回的 app_user_id 必须是字符串")

	if not app_user_id:
		raise RuntimeError("EIMS userinfo 未返回有效的 app_user_id")

	return app_user_id


def _get_user_by_eims_app_user_id(app_user_id: str):
	if not frappe.get_meta("User").has_field(EIMS_USER_ID_FIELD):
		frappe.throw(_("ERP 尚未创建 EIMS App User ID 字段，请先执行 migrate"))

	user_names = frappe.get_all(
		"User",
		filters={EIMS_USER_ID_FIELD: str(app_user_id)},
		pluck="name",
		limit_page_length=2,
	)
	if not user_names:
		raise EIMSUserBindingError(
			f"EIMS app_user_id {app_user_id} has no corresponding ERP User"
		)
	if len(user_names) > 1:
		raise EIMSUserBindingError(
			f"EIMS app_user_id {app_user_id} matches multiple ERP Users"
		)

	user = frappe.get_doc("User", user_names[0])
	if not user.enabled:
		raise EIMSUserBindingError(f"ERP User {user.name} is disabled")
	return user
