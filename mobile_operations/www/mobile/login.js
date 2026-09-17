frappe.ready(function () {
	const form = document.getElementById("mobile-login-form");
	const user_input = document.getElementById("mobile-login-user");
	const password_input = document.getElementById("mobile-login-password");
	const submit_button = form.querySelector(".mobile-login-submit");
	const status = document.querySelector("[data-region='status']");
	const redirect_to = safe_mobile_redirect(new URLSearchParams(window.location.search).get("redirect-to"));

	document.querySelector("[data-action='toggle-password']").addEventListener("click", function () {
		const is_password = password_input.type === "password";
		password_input.type = is_password ? "text" : "password";
		this.textContent = is_password ? __("隐藏") : __("显示");
	});

	document.querySelector("[data-action='show-email-link']")?.addEventListener("click", function () {
		document.querySelector("[data-region='email-panel']").hidden = false;
		this.hidden = true;
		document.querySelector("[data-field='email-link']")?.focus();
	});

	document.querySelector("[data-action='show-forgot']")?.addEventListener("click", function () {
		form.hidden = true;
		document.querySelector("[data-region='forgot-panel']").hidden = false;
		document.querySelectorAll(".mobile-login-divider, .mobile-login-providers, [data-action='show-email-link']").forEach((element) => {
			element.hidden = true;
		});
		document.querySelector("[data-field='forgot-email']")?.focus();
	});

	document.querySelector("[data-action='back-login']")?.addEventListener("click", function () {
		form.hidden = false;
		document.querySelector("[data-region='forgot-panel']").hidden = true;
		document.querySelectorAll(".mobile-login-divider, .mobile-login-providers, [data-action='show-email-link']").forEach((element) => {
			element.hidden = false;
		});
	});

	document.querySelector("[data-action='send-forgot']")?.addEventListener("click", function () {
		const email = document.querySelector("[data-field='forgot-email']")?.value.trim();
		if (!email) {
			set_login_status(status, __("请输入邮箱"), "#d14b4b");
			return;
		}

		this.disabled = true;
		frappe.call({
			method: "frappe.core.doctype.user.user.reset_password",
			args: { user: email },
			callback: () => {
				set_login_status(status, __("如果账号存在，重置密码邮件已发送，请查收邮箱"), "#278154");
				this.disabled = false;
			},
			error: () => {
				set_login_status(status, __("操作失败，请稍后重试"), "#d14b4b");
				this.disabled = false;
			},
		});
	});

	document.querySelector("[data-action='send-email-link']")?.addEventListener("click", function () {
		const email_input = document.querySelector("[data-field='email-link']");
		const email = email_input?.value.trim();
		if (!email) {
			set_login_status(status, __("请输入邮箱"), "#d14b4b");
			return;
		}

		this.disabled = true;
		frappe.call({
			method: "frappe.www.login.send_login_link",
			args: { email },
			callback: () => {
				set_login_status(status, __("登录链接已发送，请检查邮箱"), "#278154");
				this.disabled = false;
			},
			error: () => {
				set_login_status(status, __("登录链接发送失败，请稍后重试"), "#d14b4b");
				this.disabled = false;
			},
		});
	});

	form.addEventListener("submit", function (event) {
		event.preventDefault();
		const usr = user_input.value.trim();
		const pwd = password_input.value;
		if (!usr || !pwd) return;

		submit_button.disabled = true;
		set_login_status(status, __("正在登录..."), "#777");
		frappe.call({
			type: "POST",
			url: "/login",
			args: { cmd: "login", usr, pwd },
			freeze: true,
			callback: (response) => {
				if (response.message === "Logged In" || response.message === "No App") {
					window.location.replace(redirect_to);
					return;
				}
				if (response.message === "Password Reset" && response.redirect_to) {
					window.location.replace(response.redirect_to);
					return;
				}
				if (response.verification) {
					set_login_status(status, __("当前账号需要二次验证，请先使用标准登录页完成验证"), "#a86513");
				} else {
					set_login_status(status, __("登录未完成，请重试"), "#d14b4b");
				}
				submit_button.disabled = false;
			},
			error: (xhr) => {
				set_login_status(status, get_login_error(xhr), "#d14b4b");
				submit_button.disabled = false;
			},
		});
	});
});

function safe_mobile_redirect(value) {
	return value && value.startsWith("/mobile") ? value : "/mobile";
}

function set_login_status(element, message, color) {
	element.textContent = message;
	element.style.color = color;
}

function get_login_error(xhr) {
	try {
		const response = xhr.responseJSON || {};
		const messages = JSON.parse(response._server_messages || "[]");
		if (messages.length) return JSON.parse(messages[0]).message || __("登录失败，请检查账号和密码");
	} catch (error) {
		// Fall through to the generic message. Login errors must not reveal account state.
	}
	return __("登录失败，请检查账号和密码");
}
