const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { deflateRawSync } = require("node:zlib");
const modulePath = path.join(__dirname, "../deeplinkerp_branding/public/js/purchase_order_export.js");
const exporter = fs.existsSync(modulePath) ? require(modulePath) : {};
const encoder = new TextEncoder();
const decoder = new TextDecoder();
function production(name) {
	assert.equal(typeof exporter[name], "function", `${name} must be available`);
	return exporter[name];
}
function fixtureCRC(bytes) {
	let crc = 0xffffffff;
	for (const byte of bytes) {
		crc ^= byte;
		for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
	}
	return (crc ^ 0xffffffff) >>> 0;
}
function compressedZip(entries) {
	const local = [], central = [];
	let offset = 0;
	for (const { name, data } of entries) {
		const filename = Buffer.from(name), raw = Buffer.from(data), compressed = deflateRawSync(raw), crc = fixtureCRC(raw);
		const header = Buffer.alloc(30), directory = Buffer.alloc(46);
		for (const [position, value] of [[0, 0x04034b50], [14, crc], [18, compressed.length], [22, raw.length]]) header.writeUInt32LE(value, position);
		for (const [position, value] of [[4, 20], [6, 0x800], [8, 8], [26, filename.length]]) header.writeUInt16LE(value, position);
		for (const [position, value] of [[0, 0x02014b50], [16, crc], [20, compressed.length], [24, raw.length], [42, offset]]) directory.writeUInt32LE(value, position);
		for (const [position, value] of [[4, 20], [6, 20], [8, 0x800], [10, 8], [28, filename.length]]) directory.writeUInt16LE(value, position);
		local.push(header, filename, compressed); central.push(directory, filename);
		offset += header.length + filename.length + compressed.length;
	}
	const tail = Buffer.alloc(22), directory = Buffer.concat(central);
	tail.writeUInt32LE(0x06054b50, 0); tail.writeUInt16LE(entries.length, 8); tail.writeUInt16LE(entries.length, 10);
	tail.writeUInt32LE(directory.length, 12); tail.writeUInt32LE(offset, 16);
	return Buffer.concat([...local, directory, tail]);
}
const escapeXML = (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function worksheet(headers, values = []) {
	const cell = (value, index, row) => typeof value === "number" ? `<c r="${String.fromCharCode(65 + index)}${row}" s="7" t="n"><v>${value}</v></c>` : `<c r="${String.fromCharCode(65 + index)}${row}" s="4" t="inlineStr"><is><t xml:space="preserve">${escapeXML(value)}</t></is></c>`;
	const rows = [headers, ...values].map((row, index) => `<row r="${index + 1}" spans="1:${headers.length}">${row.map((value, column) => cell(value, column, index + 1)).join("")}</row>`).join("");
	return `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:${String.fromCharCode(64 + headers.length)}${values.length + 1}"/><cols><col min="5" max="${headers.length}" width="14" style="4"/><col min="${headers.length}" max="${headers.length}" width="18"/></cols><sheetData>${rows}</sheetData><pageMargins left="0.7"/></worksheet>`;
}
function entries(xml) {
	return [
		{ name: "[Content_Types].xml", data: encoder.encode('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>') },
		{ name: "xl/workbook.xml", data: encoder.encode('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="采购订单" sheetId="1"/></sheets></workbook>') },
		{ name: "xl/styles.xml", data: encoder.encode('<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts/></styleSheet>') },
		{ name: "xl/worksheets/sheet1.xml", data: encoder.encode(xml) },
	];
}
const headers = ["序号", "创建人", "供应商名称", "已预付", "往来单位科目货币", "编号", "创建人"];
const values = [[1, "buyer@example.com", '供应商 &\n<中文> "引号"', 0, "USD", "PO-1", "buyer@example.com"]];

test("ZIP roundtrip preserves every entry's bytes and emits a standard CRC32", async () => {
	assert.equal(production("crc32")(encoder.encode("123456789")), 0xcbf43926);
	const source = entries(worksheet(headers, values));
	const archive = production("writeZip")(source);
	const decoded = await production("readZip")(archive);
	assert.deepEqual(decoded.map((entry) => entry.name), source.map((entry) => entry.name));
	for (let index = 0; index < source.length; index++) assert.deepEqual(decoded[index].data, source[index].data);
});

test("deflated native-style ZIP is rewritten with requested owner order, numeric zero and currency intact", async () => {
	const xml = worksheet(headers, values);
	const source = entries(xml);
	const rewritten = await production("removeNativeOwner")(compressedZip(source), { expectedColumns: 6, ownerLabels: ["创建人"] });
	const decoded = await production("readZip")(rewritten);
	const output = decoder.decode(decoded.find((entry) => entry.name.endsWith("sheet1.xml")).data);
	assert.ok(output.includes('<dimension ref="A1:F2"/>'));
	assert.ok(output.includes('<c r="B2" s="4" t="inlineStr"><is><t xml:space="preserve">buyer@example.com</t></is></c>'));
	assert.ok(output.includes('<c r="D2" s="7" t="n"><v>0</v></c>'));
	assert.ok(output.includes('<c r="E2" s="4" t="inlineStr"><is><t xml:space="preserve">USD</t></is></c>'));
	assert.ok(output.includes('供应商 &amp;\n&lt;中文&gt; "引号"'));
	assert.equal(/r="G[12]"/.test(output), false);
	assert.ok(output.includes('min="5" max="6" width="14" style="4"'));
	assert.equal(output.includes('min="7"'), false);
	assert.equal(output.includes('spans="1:7"'), false);
	for (const original of source.filter((entry) => !entry.name.endsWith("sheet1.xml"))) assert.deepEqual(decoded.find((entry) => entry.name === original.name).data, original.data);
});

test("hiding owner removes only the native appended column even for a header-only workbook", () => {
	const xml = worksheet(["序号", "编号", "供应商名称", "已预付", "创建人"]);
	const output = production("stripTrailingOwner")(xml, { expectedColumns: 4, ownerLabels: ["创建人"] });
	assert.ok(output.includes('ref="A1:D1"'));
	assert.equal(output.includes("创建人"), false);
	assert.equal(output.includes('r="E1"'), false);
});

test("unexpected owner header or workbook dimensions fail before returning a downloadable workbook", async () => {
	assert.throws(() => production("stripTrailingOwner")(worksheet(["序号", "编号", "公司"]), { expectedColumns: 2, ownerLabels: ["创建人"] }), /owner|创建人/i);
	assert.throws(() => production("stripTrailingOwner")(worksheet(headers).replace("A1:G1", "A1:H1"), { expectedColumns: 6, ownerLabels: ["创建人"] }), /column|列|shape/i);
	const multiple = [...entries(worksheet(headers)), { name: "xl/worksheets/sheet2.xml", data: encoder.encode(worksheet(headers)) }];
	await assert.rejects(() => production("removeNativeOwner")(compressedZip(multiple), { expectedColumns: 6, ownerLabels: ["创建人"] }), /sheet|工作表/i);
});

test("ZIP64, corrupt CRC and oversized archives are explicitly rejected", async () => {
	const archive = compressedZip(entries(worksheet(headers)));
	const zip64 = Buffer.from(archive); zip64.writeUInt16LE(0xffff, zip64.length - 22 + 10);
	await assert.rejects(() => production("readZip")(zip64), /ZIP64/i);
	const corrupt = Buffer.from(archive), central = corrupt.indexOf(Buffer.from([0x50, 0x4b, 0x01, 0x02]));
	corrupt.writeUInt32LE(0, central + 16);
	await assert.rejects(() => production("readZip")(corrupt), /CRC|损坏/i);
	await assert.rejects(() => production("readZip")(archive, { maxArchiveBytes: 50 }), /size|大小|过大/i);
});

test("native export request retains exact filters, requests Excel with same-origin CSRF and rejects errors", async () => {
	const args = { fields: ["name", "advance_paid", "party_account_currency"], filters: [["Purchase Order", "company", "=", "Company A"]], or_filters: [["Purchase Order", "supplier_name", "like", "%中文%"]], start: 0, file_format_type: "Excel" };
	const archive = compressedZip(entries(worksheet(["序号", "编号", "已预付", "往来单位科目货币", "创建人"])));
	let actualRequest;
	const root = { location: { href: "http://erp.localhost/desk/purchase-order", origin: "http://erp.localhost" }, frappe: { csrf_token: "test-csrf", request: { url: "/" } }, fetch: async (url, options) => { actualRequest = { url, options }; return new Response(archive, { headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" } }); } };
	const result = await production("fetchNativeWorkbook")(root, args);
	assert.deepEqual(result, new Uint8Array(archive));
	assert.equal(actualRequest.options.credentials, "same-origin");
	assert.equal(actualRequest.options.headers["X-Frappe-CSRF-Token"], "test-csrf");
	assert.equal(actualRequest.options.method, "POST");
	const body = new URLSearchParams(actualRequest.options.body);
	assert.deepEqual(JSON.parse(body.get("filters")), args.filters);
	assert.deepEqual(JSON.parse(body.get("or_filters")), args.or_filters);
	assert.equal(body.get("cmd"), "frappe.desk.reportview.export_query");
	assert.equal(body.get("file_format_type"), "Excel");
	root.fetch = async () => new Response('{"exception":"PermissionError"}', { status: 403, headers: { "Content-Type": "application/json" } });
	await assert.rejects(() => production("fetchNativeWorkbook")(root, args), /403|permission|权限/i);
	root.fetch = async () => new Response('{"exception":"ValidationError"}', { headers: { "Content-Type": "application/json" } });
	await assert.rejects(() => production("fetchNativeWorkbook")(root, args), /错误响应/);
	root.frappe.request.url = "https://other-site.example/";
	await assert.rejects(() => production("fetchNativeWorkbook")(root, args), /origin|同源/i);
});
