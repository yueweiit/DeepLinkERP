frappe.pages["mes-portal"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("MES 系统"),
		single_column: true,
	});

	const mes_url = "https://lemos-case.com/mes";

	page.set_primary_action(__("新窗口打开"), () => {
		window.open(mes_url, "_blank", "noopener");
	});

	$(page.body).html(`
		<div class="mes-portal-wrapper">
			<div class="mes-portal-fallback">
				<div>
					<div class="mes-portal-fallback-title">${__("正在加载 MES 系统")}</div>
					<div class="mes-portal-fallback-text">
						${__("如果页面无法显示，请使用右上角按钮在新窗口打开。")}
					</div>
				</div>
			</div>
			<iframe
				class="mes-portal-frame"
				src="${mes_url}"
				title="${__("MES 系统")}"
				allowfullscreen>
			</iframe>
		</div>
	`);

	$(`<style>
		.mes-portal-wrapper {
			position: relative;
			height: calc(100vh - 126px);
			min-height: 520px;
			background: var(--fg-color);
			border: 1px solid var(--border-color);
			border-radius: var(--border-radius-md);
			overflow: hidden;
		}

		.mes-portal-fallback {
			position: absolute;
			inset: 0;
			display: flex;
			align-items: center;
			justify-content: center;
			padding: 24px;
			text-align: center;
			color: var(--text-muted);
			background: var(--fg-color);
		}

		.mes-portal-fallback-title {
			margin-bottom: 8px;
			font-size: 16px;
			font-weight: 600;
			color: var(--text-color);
		}

		.mes-portal-fallback-text {
			font-size: 13px;
		}

		.mes-portal-frame {
			position: absolute;
			inset: 0;
			width: 100%;
			height: 100%;
			border: 0;
			background: #fff;
		}
	</style>`).appendTo(page.body);
};
