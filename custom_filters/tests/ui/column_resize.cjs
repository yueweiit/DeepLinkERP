// Run with Playwright on NODE_PATH; uses local Bench assets and no database.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require("playwright");
const app = path.resolve(__dirname, "../../..");
const frappe = path.resolve(app, "../frappe/frappe/public");
const manifest = JSON.parse(fs.readFileSync(path.resolve(app, "../../sites/assets/assets.json")));
const files = {
	"/": path.join(__dirname, "column_resize.html"),
	"/jquery.js": path.join(frappe, "js/lib/jquery/jquery.min.js"),
	"/native.css": path.join(frappe, manifest["desk.bundle.css"].replace("/assets/frappe/", "")),
	"/user_settings.js": path.join(frappe, "js/frappe/model/user_settings.js"),
	"/list_view.js": path.join(frappe, "js/frappe/list/list_view.js"),
};
for (const name of ["grid_column_resize", "list_column_resize", "list_horizontal_scroll"]) {
	for (const ext of ["js", "css"]) files[`/${ext}/${name}.${ext}`] = path.join(app, `custom_filters/public/${ext}/${name}.${ext}`);
}
const server = http.createServer((req, res) => {
	const file = files[req.url];
	if (!file) { res.writeHead(404).end(); return; }
	let content = fs.readFileSync(file, "utf8");
	if (req.url === "/list_view.js") content = content.replace(/^import .*;$/gm, "");
	res.setHeader("Content-Type", file.endsWith(".css") ? "text/css" : file.endsWith(".js") ? "text/javascript" : "text/html");
	res.end(content);
});
const HANDLE = ".custom-filters-grid-column-resize-handle";
const head = (field, id = "sales") => `#${id} .list-header-subject > .${field}`;
const width = locator => locator.evaluate(el => Math.round(el.getBoundingClientRect().width));
async function drag(page, selector, delta) {
	const handle = page.locator(`${selector} ${HANDLE}`);
	await handle.scrollIntoViewIfNeeded();
	const rect = await handle.boundingBox();
	await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
	await page.mouse.down();
	await page.mouse.move(rect.x + rect.width / 2 + delta, rect.y + rect.height / 2, { steps: 8 });
	await page.mouse.up();
}
async function settle(page) {
	await page.evaluate(async () => {
		await Promise.all([CustomFiltersGridColumnResize.save_queue, CustomFiltersListColumnResize.save_queue]);
		await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
	});
}
async function aligned(page, field, expected) {
	assert.equal(await width(page.locator(head(field))), expected);
	const index = await page.locator(head(field)).getAttribute("data-cf-list-column");
	const values = await page.locator(`#sales .list-row [data-cf-list-column="${index}"]`).evaluateAll(nodes => nodes.map(el => Math.round(el.getBoundingClientRect().width)));
	assert.ok(values.length > 0 && values.every(w => w === expected), `${field} row/header widths differ`);
}
async function main() {
	await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
	let browser;
	try {
		browser = await chromium.launch({
			headless: true,
			executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH,
			args: ["--no-sandbox"],
		});
		const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
		const page = await context.newPage();
		const errors = [];
		page.on("pageerror", error => errors.push(error.message));
		await page.goto(`http://127.0.0.1:${server.address().port}`);
		await page.waitForTimeout(1000);
		await page.waitForSelector(`${head("customer_name")} ${HANDLE}`);
		const original = await width(page.locator(head("customer_name")));
		const personOriginal = await width(page.locator(head("sales_person")));
		assert.equal(await page.locator(`#sales .list-header-subject ${HANDLE}`).count(), 7);
		await drag(page, head("customer_name"), 110);
		await page.evaluate(() => render_list("sales"));
		await settle(page);
		await aligned(page, "customer_name", original + 110);
		await drag(page, head("sales_person"), -60);
		await settle(page);
		await aligned(page, "sales_person", personOriginal - 60);
		await page.reload();
		await page.waitForSelector(`${head("customer_name")} ${HANDLE}`);
		await aligned(page, "customer_name", original + 110);
		await aligned(page, "sales_person", personOriginal - 60);
		console.log("PASS: drag, pending-save rerender, multiple columns and reload");

		const statusOriginal = await width(page.locator(head("status")));
		await drag(page, head("status"), -35);
		await settle(page);
		await aligned(page, "status", statusOriginal - 35);
		await page.evaluate(() => render_list("sales", [0, 4, 2, 3, 5, 1, 6], 25));
		await settle(page);
		await aligned(page, "sales_person", personOriginal - 60);
		await aligned(page, "status", statusOriginal - 35);
		await page.evaluate(() => { document.querySelectorAll("#sales .sales_person").forEach(el => { el.style.width = "400px"; el.style.flex = "1 0 400px"; }); });
		await aligned(page, "sales_person", personOriginal - 60);
		console.log("PASS: status cells, reordered fields, new rows and native auto-sizing");

		await page.evaluate(() => {
			document.querySelector("#sales").style.display = "none";
			document.querySelector("#purchase").style.display = "block";
			cur_list = frappe.views.list_view.purchase;
			CustomFiltersListColumnResize.schedule_scan();
		});
		await page.waitForSelector(`${head("customer_name", "purchase")} ${HANDLE}`);
		assert.equal(await width(page.locator(head("customer_name", "purchase"))), original);
		await drag(page, head("customer_name", "purchase"), 40);
		await settle(page);
		await page.evaluate(() => {
			document.querySelector("#sales").style.display = "block";
			document.querySelector("#purchase").style.display = "none";
			cur_list = frappe.views.list_view.sales;
			CustomFiltersListColumnResize.schedule_scan();
		});
		await settle(page);
		await aligned(page, "customer_name", original + 110);
		const personHandle = page.locator(`${head("sales_person")} ${HANDLE}`);
		await personHandle.dblclick();
		await settle(page);
		await aligned(page, "sales_person", personOriginal);
		await personHandle.press("ArrowRight");
		await settle(page);
		await aligned(page, "sales_person", personOriginal + 10);
		assert.equal(await page.evaluate(() => sort_clicks), 0);
		await page.locator(`${head("customer_name")} [data-sort-by]`).click();
		assert.equal(await page.evaluate(() => sort_clicks), 1);
		console.log("PASS: document isolation, reset, keyboard resize and sorting");

		await page.setViewportSize({ width: 600, height: 900 });
		await settle(page);
		assert.equal(await page.locator(`#sales ${HANDLE}:visible`).count(), 0);
		await page.setViewportSize({ width: 1280, height: 900 });
		await settle(page);
		await aligned(page, "customer_name", original + 110);
		const gridHead = name => `#grid .grid-heading-row [data-fieldname="${name}"]`;
		await drag(page, gridHead("qty"), 30);
		await settle(page);
		await drag(page, gridHead("rate"), 45);
		await settle(page);
		const settings = await page.evaluate(() => JSON.parse(localStorage.getItem("user-settings"))["Sales Order"]);
		assert.deepEqual(settings.GridColumnWidths.items, { qty: 190, rate: 225 });
		assert.deepEqual(settings.GridColumnWidths.taxes, { amount: 210 });
		assert.equal(settings.List.sort_by, "modified");
		assert.equal(settings.ListColumnWidths.List["Subject:customer_name"], original + 110);
		console.log("PASS: mobile layout, child grids and unrelated settings retained");

		await page.evaluate(() => {
			window.scan_count = 0;
			for (const controller of [CustomFiltersGridColumnResize, CustomFiltersListColumnResize]) {
				const scan = controller.scan.bind(controller);
				controller.scan = () => { scan_count++; scan(); };
			}
		});
		await page.waitForTimeout(300);
		assert.ok(await page.evaluate(() => scan_count < 4), "Observers must settle while idle");
		await page.evaluate(() => render_list("sales", [0, 1, 2, 3, 4, 5, 6], 2500));
		await settle(page);
		await aligned(page, "customer_name", original + 110);
		await page.locator(`${head("crm_sales_order_no")} ${HANDLE}`).press("End");
		await settle(page);
		await aligned(page, "crm_sales_order_no", 1200);
		await page.locator(head("customer_name")).scrollIntoViewIfNeeded();
		await settle(page);
		assert.ok(await page.locator("#sales .result-container").evaluate(el => el.scrollWidth > el.clientWidth));
		assert.ok(await page.locator(".custom-filters-list-horizontal-scrollbar.is-visible").count() > 0);
		await page.screenshot({ path: process.env.SCREENSHOT_PATH || "/tmp/custom-filters-column-resize.png" });
		assert.deepEqual(errors, []);
		console.log("PASS: idle observers, 2500 rows, maximum width and scrollbar");
	} finally {
		await browser?.close();
		server.close();
	}
}
main().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
