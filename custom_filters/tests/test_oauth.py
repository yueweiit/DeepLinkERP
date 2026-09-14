import base64
import json
import pickle
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from custom_filters.overrides import oauth


class TestEIMSOAuth(TestCase):
	def test_decode_legacy_frappe_state(self):
		payload = {
			"site": "https://erp.example.com",
			"token": "legacy-token",
			"redirect_to": "/desk",
		}
		state = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

		with patch.object(oauth.frappe.utils, "get_url", return_value=payload["site"]):
			self.assertEqual(oauth._decode_legacy_frappe_state(state), payload)

	def test_decode_legacy_frappe_state_rejects_other_site(self):
		payload = {
			"site": "https://other.example.com",
			"token": "legacy-token",
		}
		state = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

		with patch.object(oauth.frappe.utils, "get_url", return_value="https://erp.example.com"):
			self.assertIsNone(oauth._decode_legacy_frappe_state(state))

	@patch.object(
		oauth,
		"_decode_legacy_frappe_state",
		return_value={"site": "https://erp.example.com", "token": "legacy-token", "redirect_to": "/desk"},
	)
	@patch.object(oauth, "sanitize_redirect", side_effect=lambda value: value)
	def test_legacy_callback_restarts_pkce_flow(self, _sanitize_redirect, _decode_state):
		local = SimpleNamespace(response={})
		with patch.object(oauth.frappe, "local", local):
			oauth.login_via_eims("authorization-code", "legacy-state")

		self.assertEqual(local.response["type"], "redirect")
		self.assertEqual(
			local.response["location"],
			"/api/method/custom_filters.overrides.oauth.start_eims_login?redirect_to=%2Fdesk",
		)

	def test_eims_referrer_matches_authorization_origin(self):
		with patch.object(
			oauth.frappe,
			"get_request_header",
			return_value="http://192.168.5.238:8006/",
		), patch.object(oauth, "_get_eims_provider", return_value="eims"), patch.object(
			oauth,
			"get_oauth2_providers",
			return_value={
				"eims": {
					"flow_params": {
						"authorize_url": "http://192.168.5.238:8006/oauth/authorize"
					}
				}
			},
		):
			self.assertTrue(oauth._is_eims_referrer())

	def test_other_referrer_does_not_start_eims_login(self):
		with patch.object(
			oauth.frappe,
			"get_request_header",
			return_value="http://192.168.5.238:8001/desk",
		):
			self.assertFalse(oauth._is_eims_referrer())

	def test_eims_entry_supports_no_referrer_fetch_metadata(self):
		local = SimpleNamespace(args={})
		headers = {
			"Referer": "",
			"Sec-Fetch-Site": "same-site",
			"Sec-Fetch-Mode": "navigate",
			"Sec-Fetch-Dest": "document",
		}
		with patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe,
			"get_request_header",
			side_effect=lambda key, default="": headers.get(key, default),
		), patch.object(oauth, "_is_eims_referrer", return_value=False):
			self.assertTrue(oauth._is_eims_entry_request())

	def test_direct_entry_without_eims_signal_is_not_redirected(self):
		local = SimpleNamespace(args={})
		with patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe, "get_request_header", return_value=""
		), patch.object(oauth, "_is_eims_referrer", return_value=False):
			self.assertFalse(oauth._is_eims_entry_request())

	def test_provider_name_comes_from_site_config(self):
		with patch.object(
			oauth.frappe,
			"conf",
			{"eims_social_login_key": "eims企业信息管理系统"},
		):
			self.assertEqual(oauth._get_eims_provider(), "eims企业信息管理系统")

	def test_provider_name_falls_back_to_legacy_name(self):
		with patch.object(oauth.frappe, "conf", {}):
			self.assertEqual(oauth._get_eims_provider(), "eims")

	@patch.object(oauth.frappe, "cache")
	@patch.object(oauth, "sanitize_redirect", side_effect=lambda value: value)
	@patch.object(oauth, "get_redirect_uri", return_value="https://erp.example.com/callback")
	@patch.object(oauth, "get_oauth2_providers")
	@patch.object(oauth, "get_oauth2_flow")
	def test_start_generates_server_state_and_pkce(
		self, get_oauth2_flow, get_oauth2_providers, get_redirect_uri, _sanitize_redirect, cache
	):
		flow = Mock(client_id="erp-client")
		flow.get_authorize_url.return_value = "https://eims.example.com/oauth/authorize"
		get_oauth2_flow.return_value = flow
		get_oauth2_providers.return_value = {
			"eims企业信息管理系统": {
				"flow_params": {"authorize_url": "https://eims.example.com/oauth/authorize"},
				"auth_url_data": {"response_type": "code", "scope": "openid profile"},
			}
		}

		local = SimpleNamespace(
			session=SimpleNamespace(sid="guest-session"),
			response={},
			cookie_manager=Mock(),
		)
		with patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe,
			"conf",
			{"encryption_key": "test-key", "eims_social_login_key": "eims企业信息管理系统"},
		):
			oauth.start_eims_login("/desk")

		get_oauth2_flow.assert_called_once_with("eims企业信息管理系统")
		get_redirect_uri.assert_called_once_with("eims企业信息管理系统")
		params = flow.get_authorize_url.call_args.kwargs
		self.assertEqual(params["client_id"], "erp-client")
		self.assertEqual(params["response_type"], "code")
		self.assertEqual(params["redirect_uri"], "https://erp.example.com/callback")
		self.assertEqual(params["code_challenge_method"], "S256")
		self.assertNotIn("client_secret", params)
		self.assertEqual(params["scope"], "openid profile")
		self.assertEqual(len(params["state"]), 43)
		self.assertEqual(len(params["code_challenge"]), 43)
		cache.set_value.assert_called_once()
		self.assertEqual(cache.set_value.call_args.kwargs["expires_in_sec"], oauth.EIMS_STATE_TTL_SECONDS)
		stored_state = cache.set_value.call_args.args[1]
		browser_nonce = local.cookie_manager.set_cookie.call_args.args[1]
		self.assertEqual(stored_state["session_id"], "guest-session")
		self.assertIn("browser_nonce_digest", stored_state)
		with patch.object(oauth.frappe, "conf", {"encryption_key": "test-key"}):
			self.assertEqual(oauth._state_digest(browser_nonce), stored_state["browser_nonce_digest"])
		local.cookie_manager.set_cookie.assert_called_once_with(
			oauth.EIMS_BROWSER_NONCE_COOKIE,
			browser_nonce,
			max_age=oauth.EIMS_STATE_TTL_SECONDS,
			httponly=True,
			samesite="Lax",
		)

	@patch.object(oauth.frappe, "cache")
	@patch.object(oauth, "sanitize_redirect", side_effect=lambda value: value)
	def test_state_is_consumed_once(self, _sanitize_redirect, cache):
		state = "one-time-state"
		browser_nonce = "browser-nonce"
		local = SimpleNamespace(
			session=SimpleNamespace(sid="guest-session"),
			request=SimpleNamespace(cookies={oauth.EIMS_BROWSER_NONCE_COOKIE: browser_nonce}),
			cookie_manager=Mock(),
		)
		with patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe, "conf", {"encryption_key": "test-key"}
		):
			state_digest = oauth._state_digest(state)
			cache.make_key.return_value = b"cache-key"
			cache.getdel.side_effect = [
				pickle.dumps(
					{
						"state_digest": state_digest,
						"browser_nonce_digest": oauth._state_digest(browser_nonce),
						"code_verifier": "pkce-verifier",
						"session_id": "guest-session",
					}
				),
				None,
			]
			self.assertEqual(oauth._consume_state(state)["code_verifier"], "pkce-verifier")
			with self.assertRaises(RuntimeError):
				oauth._consume_state(state)

		self.assertEqual(cache.getdel.call_count, 2)
		local.cookie_manager.delete_cookie.assert_called_once_with(oauth.EIMS_BROWSER_NONCE_COOKIE)

	@patch.object(oauth.frappe, "cache")
	def test_state_rejects_a_different_guest_browser(self, cache):
		state = "one-time-state"
		cache.make_key.return_value = b"cache-key"
		local = SimpleNamespace(
			session=SimpleNamespace(sid="Guest"),
			request=SimpleNamespace(cookies={oauth.EIMS_BROWSER_NONCE_COOKIE: "browser-b"}),
			cookie_manager=Mock(),
		)
		with patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe, "conf", {"encryption_key": "test-key"}
		):
			state_digest = oauth._state_digest(state)
			cache.getdel.return_value = pickle.dumps(
				{
					"state_digest": state_digest,
					"browser_nonce_digest": oauth._state_digest("browser-a"),
					"code_verifier": "pkce-verifier",
					"session_id": "Guest",
				}
			)
			with self.assertRaisesRegex(RuntimeError, "浏览器不匹配"):
				oauth._consume_state(state)

		local.cookie_manager.delete_cookie.assert_not_called()

	def test_normalize_app_user_id(self):
		self.assertEqual(oauth._normalize_app_user_id(12), "12")
		self.assertEqual(oauth._normalize_app_user_id("12"), "12")
		self.assertEqual(oauth._normalize_app_user_id("0012"), "0012")
		self.assertEqual(oauth._normalize_app_user_id("user-12"), "user-12")

		for value in (None, True, "", "   ", 1.5, {}, []):
			with self.subTest(value=value), self.assertRaises(RuntimeError):
				oauth._normalize_app_user_id(value)

	def test_sensitive_oauth_request_values_are_redacted_before_logging(self):
		form_dict = {
			"doc": json.dumps(
				{
					"client_id": "erp-client",
					"client_secret": "server-secret",
					"code": "authorization-code",
					"state": "oauth-state",
				}
			),
			"code": "authorization-code",
			"authCode": "authorization-code",
			"state": "oauth-state",
		}
		with patch.object(oauth.frappe, "local", SimpleNamespace(form_dict=form_dict)):
			oauth.scrub_sensitive_oauth_request_log()

		self.assertEqual(form_dict["code"], "[REDACTED]")
		self.assertEqual(form_dict["authCode"], "[REDACTED]")
		self.assertEqual(form_dict["state"], "[REDACTED]")
		self.assertEqual(form_dict["doc"]["client_secret"], "[REDACTED]")
		self.assertEqual(form_dict["doc"]["code"], "[REDACTED]")
		self.assertEqual(form_dict["doc"]["state"], "[REDACTED]")

	@patch.object(oauth.frappe, "get_doc")
	@patch.object(oauth.frappe, "get_all", return_value=["user@example.com"])
	@patch.object(oauth.frappe, "get_meta")
	def test_lookup_uses_only_eims_app_user_id(self, get_meta, get_all, get_doc):
		get_meta.return_value.has_field.return_value = True
		user = SimpleNamespace(name="user@example.com", enabled=1)
		get_doc.return_value = user

		self.assertIs(oauth._get_user_by_eims_app_user_id("user-0012"), user)

		get_all.assert_called_once_with(
			"User",
			filters={"custom_eims_app_user_id": "user-0012"},
			pluck="name",
			limit_page_length=2,
		)
		get_doc.assert_called_once_with("User", "user@example.com")

	@patch.object(oauth.frappe, "get_all", return_value=[])
	@patch.object(oauth.frappe, "get_meta")
	def test_missing_eims_binding_is_a_user_facing_binding_error(self, get_meta, get_all):
		get_meta.return_value.has_field.return_value = True

		with self.assertRaises(oauth.EIMSUserBindingError):
			oauth._get_user_by_eims_app_user_id(12)

		get_all.assert_called_once_with(
			"User",
			filters={"custom_eims_app_user_id": "12"},
			pluck="name",
			limit_page_length=2,
		)

	@patch.object(oauth.frappe, "log_error")
	@patch.object(oauth.frappe, "respond_as_web_page")
	@patch.object(
		oauth,
		"_get_user_by_eims_app_user_id",
		side_effect=oauth.EIMSUserBindingError("missing ERP user"),
	)
	@patch.object(oauth.requests, "get")
	@patch.object(oauth.requests, "post")
	@patch.object(oauth, "get_redirect_uri", return_value="https://erp.example.com/callback")
	@patch.object(oauth, "get_oauth2_providers")
	@patch.object(oauth, "get_oauth2_flow")
	@patch.object(
		oauth,
		"_consume_state",
		return_value={"redirect_to": "/desk", "code_verifier": "pkce-verifier"},
	)
	def test_missing_eims_binding_shows_actionable_page(
		self,
		_consume_state,
		get_oauth2_flow,
		get_oauth2_providers,
		get_redirect_uri,
		post,
		get,
		_get_user,
		respond_as_web_page,
		log_error,
	):
		get_oauth2_flow.return_value = SimpleNamespace(
			access_token_url="https://eims.example.com/oauth/token",
			client_id="erp-client",
			client_secret="server-secret",
		)
		get_oauth2_providers.return_value = {
			"eims": {"api_endpoint": "https://eims.example.com/oauth/userinfo"}
		}
		post.return_value = Mock(status_code=200, json=Mock(return_value={"access_token": "token"}))
		get.return_value = Mock(status_code=200, json=Mock(return_value={"app_user_id": 12}))

		with patch.object(oauth, "_get_eims_provider", return_value="eims"):
			oauth.login_via_eims("code", "state")

		respond_as_web_page.assert_called_once_with(
			"ERP 未绑定 EIMS 账号",
			"当前 EIMS 账号未在 ERP 中绑定对应用户，请联系管理员配置 EIMS App User ID 后重试。",
			http_status_code=403,
			primary_action="/login",
			primary_label="返回登录页",
			fullpage=True,
		)
		log_error.assert_called_once()

	@patch.object(oauth, "redirect_post_login")
	@patch.object(oauth, "_get_user_by_eims_app_user_id")
	@patch.object(
		oauth,
		"_consume_state",
		return_value={"redirect_to": "/app", "code_verifier": "pkce-verifier"},
	)
	@patch.object(oauth, "get_redirect_uri", return_value="https://erp.example.com/callback")
	@patch.object(oauth, "get_oauth2_providers")
	@patch.object(oauth, "get_oauth2_flow")
	@patch.object(oauth.requests, "get")
	@patch.object(oauth.requests, "post")
	def test_callback_exchanges_code_then_fetches_userinfo(
		self,
		post,
		get,
		get_oauth2_flow,
		get_oauth2_providers,
		get_redirect_uri,
		_consume_state,
		get_user,
		redirect_post_login,
	):
		get_oauth2_flow.return_value = SimpleNamespace(
			access_token_url="https://eims.example.com/oauth/token",
			client_id="erp-client",
			client_secret="server-secret",
		)
		get_oauth2_providers.return_value = {
			"eims": {"api_endpoint": "https://eims.example.com/oauth/userinfo"}
		}
		post.return_value = Mock(status_code=200, json=Mock(return_value={"access_token": "token"}))
		get.return_value = Mock(status_code=200, json=Mock(return_value={"app_user_id": 12}))
		get_user.return_value = SimpleNamespace(name="user@example.com", enabled=1, user_type="System User")

		login_manager = Mock()
		db = SimpleNamespace(commit=Mock())
		with patch.object(oauth, "_get_eims_provider", return_value="eims"), patch.object(
			oauth.frappe, "local", SimpleNamespace(login_manager=login_manager)
		), patch.object(oauth.frappe, "db", db):
			oauth.login_via_eims(" code ", "state")

		post.assert_called_once()
		self.assertEqual(post.call_args.kwargs["data"]["code"], "code")
		self.assertEqual(post.call_args.kwargs["data"]["client_secret"], "server-secret")
		self.assertEqual(post.call_args.kwargs["data"]["code_verifier"], "pkce-verifier")
		get.assert_called_once_with(
			"https://eims.example.com/oauth/userinfo",
			headers={"Accept": "application/json", "Authorization": "Bearer token"},
			timeout=oauth.OAUTH_REQUEST_TIMEOUT,
		)
		login_manager.login_as.assert_called_once_with("user@example.com")
		db.commit.assert_called_once_with()
		redirect_post_login.assert_called_once_with(
			desk_user=True,
			redirect_to="/app",
			provider="eims",
		)


class TestDingTalkOAuth(TestCase):
	def test_start_generates_server_state_and_dingtalk_authorization_url(self):
		flow = SimpleNamespace(
			client_id="ding-client",
			client_secret="server-secret",
			get_authorize_url=Mock(return_value="https://login.dingtalk.com/oauth2/auth?..."),
		)
		cache = Mock()
		local = SimpleNamespace(
			session=SimpleNamespace(sid="guest-session"),
			response={},
			cookie_manager=Mock(),
		)
		provider_config = {
			"api_endpoint": oauth.DINGTALK_USERINFO_URL,
			"flow_params": {"authorize_url": "https://login.dingtalk.com/oauth2/auth"},
			"auth_url_data": {"scope": "openid", "prompt": "consent", "corpId": "corp-001"},
		}

		with patch.object(oauth, "_get_dingtalk_provider", return_value="dingtalk"), patch.object(
			oauth, "get_oauth2_providers", return_value={"dingtalk": provider_config}
		), patch.object(oauth, "get_oauth2_flow", return_value=flow), patch.object(
			oauth, "get_redirect_uri", return_value="https://erp.example.com/dingtalk/callback"
		), patch.object(oauth, "sanitize_redirect", side_effect=lambda value: value), patch.object(
			oauth.frappe, "cache", cache
		), patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe, "conf", {"encryption_key": "test-key"}
		):
			oauth.start_dingtalk_login("/desk")

		params = flow.get_authorize_url.call_args.kwargs
		self.assertEqual(params["client_id"], "ding-client")
		self.assertEqual(params["redirect_uri"], "https://erp.example.com/dingtalk/callback")
		self.assertEqual(params["responseType"], "code")
		self.assertEqual(params["response_type"], "code")
		self.assertEqual(params["scope"], "openid")
		self.assertEqual(params["prompt"], "consent")
		self.assertEqual(params["corpId"], "corp-001")
		self.assertNotIn("client_secret", params)
		self.assertEqual(len(params["state"]), 43)
		cache.set_value.assert_called_once()
		self.assertEqual(cache.set_value.call_args.kwargs["expires_in_sec"], oauth.DINGTALK_STATE_TTL_SECONDS)
		self.assertEqual(cache.set_value.call_args.args[1]["session_id"], "guest-session")
		local.cookie_manager.set_cookie.assert_called_once_with(
			oauth.DINGTALK_BROWSER_NONCE_COOKIE,
			local.cookie_manager.set_cookie.call_args.args[1],
			max_age=oauth.DINGTALK_STATE_TTL_SECONDS,
			httponly=True,
			samesite="Lax",
		)
		self.assertEqual(local.response["type"], "redirect")

	def test_dingtalk_state_is_consumed_once_and_requires_browser_nonce(self):
		state = "one-time-state"
		browser_nonce = "browser-nonce"
		cache = Mock()
		cache.make_key.return_value = b"cache-key"
		cache.getdel.side_effect = [
			pickle.dumps(
				{
					"state_digest": "placeholder",
					"browser_nonce_digest": "placeholder",
					"session_id": "guest-session",
				}
			),
			None,
		]
		local = SimpleNamespace(
			session=SimpleNamespace(sid="guest-session"),
			request=SimpleNamespace(cookies={oauth.DINGTALK_BROWSER_NONCE_COOKIE: browser_nonce}),
			cookie_manager=Mock(),
		)

		with patch.object(oauth.frappe, "cache", cache), patch.object(oauth.frappe, "local", local), patch.object(
			oauth.frappe, "conf", {"encryption_key": "test-key"}
		):
			state_digest = oauth._state_digest(state)
			cache.getdel.side_effect = [
				pickle.dumps(
					{
						"state_digest": state_digest,
						"browser_nonce_digest": oauth._state_digest(browser_nonce),
						"session_id": "guest-session",
					}
				),
				None,
			]
			self.assertEqual(oauth._consume_dingtalk_state(state)["session_id"], "guest-session")
			with self.assertRaises(RuntimeError):
				oauth._consume_dingtalk_state(state)

		local.cookie_manager.delete_cookie.assert_called_once_with(oauth.DINGTALK_BROWSER_NONCE_COOKIE)

	@patch.object(oauth, "redirect_post_login")
	@patch.object(oauth, "_get_user_by_dingtalk_identity")
	@patch.object(
		oauth,
		"_consume_dingtalk_state",
		return_value={"redirect_to": "/desk"},
	)
	@patch.object(oauth, "_get_dingtalk_provider", return_value="dingtalk")
	@patch.object(
		oauth,
		"get_oauth2_providers",
		return_value={"dingtalk": {"api_endpoint": oauth.DINGTALK_USERINFO_URL}},
	)
	@patch.object(oauth, "get_oauth2_flow")
	@patch.object(oauth.requests, "get")
	@patch.object(oauth.requests, "post")
	def test_callback_exchanges_dingtalk_code_then_fetches_userinfo(
		self,
		post,
		get,
		get_oauth2_flow,
		_get_oauth2_providers,
		_get_provider,
		_consume_state,
		get_user,
		redirect_post_login,
	):
		get_oauth2_flow.return_value = SimpleNamespace(
			client_id="ding-client",
			client_secret="server-secret",
			access_token_url="https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
		)
		post.return_value = Mock(status_code=200, json=Mock(return_value={"accessToken": "user-token"}))
		get.return_value = Mock(
			status_code=200,
			json=Mock(return_value={"unionId": "union-001", "openId": "open-001"}),
		)
		get_user.return_value = SimpleNamespace(
			name="user@example.com",
			enabled=1,
			user_type="System User",
			custom_dingtalk_union_id="union-001",
			custom_dingtalk_open_id="open-001",
		)
		login_manager = Mock()
		db = SimpleNamespace(commit=Mock())

		with patch.object(oauth.frappe, "local", SimpleNamespace(login_manager=login_manager)), patch.object(
			oauth.frappe, "db", db
		):
			oauth.login_via_dingtalk(authCode="auth-code", state="state")

		post.assert_called_once_with(
			"https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
			json={
				"clientId": "ding-client",
				"clientSecret": "server-secret",
				"code": "auth-code",
				"grantType": "authorization_code",
			},
			headers={"Accept": "application/json", "Content-Type": "application/json"},
			timeout=oauth.OAUTH_REQUEST_TIMEOUT,
		)
		get.assert_called_once_with(
			oauth.DINGTALK_USERINFO_URL,
			headers={"Accept": "application/json", "x-acs-dingtalk-access-token": "user-token"},
			timeout=oauth.OAUTH_REQUEST_TIMEOUT,
		)
		get_user.assert_called_once_with("union-001", "open-001", {"unionId": "union-001", "openId": "open-001"})
		login_manager.login_as.assert_called_once_with("user@example.com")
		db.commit.assert_called_once_with()
		redirect_post_login.assert_called_once_with(
			desk_user=True,
			redirect_to="/desk",
			provider="dingtalk",
		)

	def test_dingtalk_identity_lookup_prefers_explicit_ids(self):
		user = SimpleNamespace(
			name="user@example.com",
			enabled=1,
			custom_dingtalk_union_id="union-001",
			custom_dingtalk_open_id="open-001",
		)
		meta = Mock()
		meta.has_field.return_value = True

		with patch.object(oauth.frappe, "get_meta", return_value=meta), patch.object(
			oauth.frappe, "get_all", side_effect=[["user@example.com"], ["user@example.com"]]
		), patch.object(oauth.frappe, "get_doc", return_value=user):
			with patch.object(oauth, "_is_dingtalk_auto_bind_enabled", return_value=False):
				with patch.object(oauth, "_bind_dingtalk_identity") as bind:
					self.assertIs(
						oauth._get_user_by_dingtalk_identity(
							"union-001", "open-001", {"unionId": "union-001", "openId": "open-001"}
						),
						user,
					)
				bind.assert_called_once_with(user, "union-001", "open-001")

	def test_phone_numbers_match_with_dingtalk_country_code(self):
		self.assertTrue(oauth._phone_numbers_match("13800138000", "+86 13800138000", "86"))
		self.assertFalse(oauth._phone_numbers_match("13800138000", "13900139000", "86"))
