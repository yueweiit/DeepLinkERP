frappe.pages["mes-portal"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("MES 系统"),
		single_column: true,
	});

	const mes_url = frappe.boot.mes_portal_url;

	if (mes_url) {
		page.set_primary_action(__("新窗口打开"), () => {
			window.open(mes_url, "_blank", "noopener");
		});
	}

	const $portal = $(`
		<div class="mes-portal-wrapper">
			<div class="mes-portal-fallback">
				<div>
					<div class="mes-portal-fallback-title">${__("正在加载 MES 系统")}</div>
					<div class="mes-portal-fallback-text">
						${__("如果页面无法显示，请检查 MES 门户地址配置。")}
					</div>
				</div>
			</div>
		</div>
	`);

	if (mes_url) {
		$("<iframe>", {
			class: "mes-portal-frame",
			title: __("MES 系统"),
			allowfullscreen: true,
		}).attr("src", mes_url).appendTo($portal);
	} else {
		$portal.find(".mes-portal-fallback-title").text(__("MES 门户地址未配置"));
	}

	$(page.body).empty().append($portal);

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
