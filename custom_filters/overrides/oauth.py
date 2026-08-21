import json
import re
from hashlib import sha256

import frappe
import frappe.utils
import requests
from frappe import _
from frappe.integrations.doctype.social_login_key.social_login_key import provider_allows_signup
from frappe.utils.oauth import (
	get_oauth2_flow,
	get_oauth2_providers,
	get_redirect_uri,
	redirect_post_login,
)


@frappe.whitelist(allow_guest=True)
def login_via_eims(code: str, state: str):
	"""
	EIMS OAuth2 SSO 自定义登录入口。

	覆盖默认的 login_via_oauth2 流程，因为：
	1. EIMS userinfo 不返回 email 字段（需要额外 scope）
	2. EIMS 用 app_username 匹配本地用户，而不是 email
	3. EIMS 返回的字段名（name, preferred_username）与 Frappe 默认不同
	"""
	provider = "eims"

	try:
		# 1. 用 code 换取 access_token
		# EIMS 的 Token 接口返回 JSON，而 rauth 默认按
		# application/x-www-form-urlencoded 解析，因此这里手动处理响应。
		flow = get_oauth2_flow(provider)
		oauth2_providers = get_oauth2_providers()
		redirect_uri = get_redirect_uri(provider)
		token_response = requests.post(
			flow.access_token_url,
			data={
				"code": code,
				"redirect_uri": redirect_uri,
				"grant_type": "authorization_code",
				"client_id": flow.client_id,
				"client_secret": flow.client_secret,
			},
			headers={"Accept": "application/json"},
			timeout=300,
		)
		try:
			token_data = token_response.json()
		except ValueError as e:
			raise RuntimeError(
				f"EIMS Token 返回了非 JSON 响应（HTTP {token_response.status_code}）"
			) from e

		access_token = token_data.get("access_token")
		if token_response.status_code >= 400 or not access_token:
			error_message = token_data.get("msg") or token_data.get("error") or token_data
			raise RuntimeError(
				f"EIMS Token 请求失败（HTTP {token_response.status_code}）：{error_message}"
			)

		# 2. 获取用户信息
		api_endpoint = oauth2_providers[provider].get("api_endpoint")
		userinfo_response = requests.get(
			api_endpoint,
			headers={
				"Accept": "application/json",
				"Authorization": f"Bearer {access_token}",
			},
			timeout=300,
		)
		try:
			info = userinfo_response.json()
		except ValueError as e:
			raise RuntimeError(
				f"EIMS UserInfo 返回了非 JSON 响应（HTTP {userinfo_response.status_code}）"
			) from e

		if userinfo_response.status_code >= 400:
			error_message = info.get("msg") or info.get("error") or info
			raise RuntimeError(
				f"EIMS UserInfo 请求失败（HTTP {userinfo_response.status_code}）：{error_message}"
			)

		# 兼容部分接口将用户信息放在 data 对象中返回的情况。
		if isinstance(info.get("data"), dict) and not info.get("sub"):
			info = info["data"]

		frappe.logger().info(f"EIMS userinfo response: {info}")

		# 3. 用 app_username 匹配本地用户
		app_username = (
			info.get("app_username")
			or info.get("preferred_username")
			or info.get("username")
			or info.get("email")
		)
		if not app_username:
			frappe.throw(_("EIMS userinfo 未返回可用于匹配 ERP 用户的用户名字段"))

		user = _get_or_create_user(app_username, info)

		# 4. 设置 social login userid
		sub = info.get("sub")
		if sub and not user.get_social_login_userid(provider):
			user.set_social_login_userid(provider, userid=sub)

		# 5. 登录用户
		frappe.local.login_manager.login_as(user.name)

		# 6. 设置重定向
		redirect_to = frappe.local.response.get("location") or "/app"
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = redirect_to

	except Exception as e:
		frappe.log_error(f"EIMS SSO login failed: {e}")
		frappe.throw(_("EIMS 登录失败：{0}").format(str(e)))


def _get_or_create_user(app_username: str, data: dict):
	"""获取或创建本地用户"""
	try:
		return frappe.get_doc("User", app_username)
	except frappe.DoesNotExistError:
		# ERP 中的 User 通常以邮箱作为 name，先按 username 查找，
		# 避免同一个 EIMS 用户被重复创建。
		existing_user = frappe.db.get_value("User", {"username": app_username}, "name")
		if existing_user:
			return frappe.get_doc("User", existing_user)

	# 用户不存在，检查是否允许自动创建
	if not provider_allows_signup("eims"):
		frappe.throw(
			_("用户 {0} 在 ERP 中不存在，且未开启自动注册。请联系管理员绑定账号。").format(app_username)
		)

	# 自动创建用户
	user = frappe.new_doc("User")
	user.update({
		"doctype": "User",
		"username": app_username,
		"email": _get_user_email(app_username, data),
		"first_name": _get_first_name(data),
		"last_name": _get_last_name(data),
		"enabled": 1,
		"new_password": frappe.generate_hash(),
		"user_type": "Website User",
	})

	# 添加默认角色
	if default_role := frappe.db.get_single_value("Portal Settings", "default_role"):
		user.add_roles(default_role)

	user.flags.ignore_permissions = True
	user.flags.no_welcome_mail = True
	user.save()

	return user


def _get_user_email(app_username: str, data: dict) -> str:
	"""获取 EIMS 邮箱；没有邮箱时生成稳定的内部邮箱。"""
	email = str(data.get("email") or "").strip().lower()
	if email and frappe.utils.validate_email_address(email):
		return email

	# Frappe User 必须有 email，使用稳定的内部地址满足 User.autoname。
	# 真实邮箱如果后来补充，可以在 ERP 用户资料中修改。
	username = str(app_username).strip().lower()
	slug = re.sub(r"[^a-z0-9._+-]+", "-", username).strip(".-") or "user"
	digest = sha256(username.encode("utf-8")).hexdigest()[:10]
	return f"{slug[:50]}-{digest}@eims.local"


def _get_first_name(data: dict) -> str:
	"""EIMS 返回 name（完整姓名），拆分为 first_name"""
	full_name = data.get("name", "")
	if full_name:
		# 中文名：第一个字是姓，其余是名
		if len(full_name) > 1:
			return full_name[1:]
		return full_name
	return data.get("preferred_username", "")


def _get_last_name(data: dict) -> str:
	"""EIMS 返回 name（完整姓名），拆分为 last_name"""
	full_name = data.get("name", "")
	if full_name and len(full_name) > 1:
		return full_name[0]  # 中文名第一个字是姓
	return ""
