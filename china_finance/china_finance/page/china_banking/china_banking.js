frappe.pages["china-banking"].on_page_load = function (wrapper) {
	frappe.utils.set_title(__("银行对账"));
	wrapper.china_banking = new ChinaBankingPage(wrapper);
};

frappe.pages["china-banking"].on_page_show = function () {
	frappe.utils.set_title(__("银行对账"));
};

class ChinaBankingPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("银行对账"),
			single_column: true,
		});
		// The embedded Banking app renders its own breadcrumb. Hide the Desk
		// page head so the two navigation rows do not appear one below another.
		this.page.page_head.hide();
		frappe.breadcrumbs.add("China Finance");
		this.mount_banking_app();
	}

	mount_banking_app() {
		const $main = $(this.wrapper).find(".layout-main-section").first();
		$main.css({
			padding: "0",
			overflow: "hidden",
			background: "var(--card-bg)",
		});

		$('<iframe>', {
			src: "/banking?embedded=1",
			title: __("银行对账"),
			class: "china-banking-embedded",
			frameborder: "0",
		}).css({
			display: "block",
			width: "100%",
			height: "calc(100vh - 128px)",
			minHeight: "640px",
			border: "0",
			background: "#fff",
		}).appendTo($main);
	}
}
