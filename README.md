# Mobile Operations

Mobile-first warehouse and manufacturing operation pages for ERPNext.

## Mobile entry

Open `/mobile` on a phone. Unauthenticated users are sent to `/mobile/login`,
which uses the standard Frappe login endpoint and session cookie. The mobile
shell keeps its own routes for material requests, inventory, stock movement,
and production; desktop Desk is only opened through an explicit
`电脑端处理` action.

## Mobile BOM workspace

The Production tab (`/mobile/production`) opens the BOM list. Search by BOM
number, finished item code/name or specification, filter by company/status,
and open a BOM to see its components, exploded materials and existing operations.
Enter a production quantity to preview proportional component requirements;
this does not change the BOM or create a production order.

Users with BOM permissions can create BOMs, edit drafts and submit them from
the phone. The editor covers company, finished item, base quantity,
specification, components and scrap rates when those custom fields exist.
Specifications follow the site's field configuration; values fetched from the
finished item are filled automatically.
New components use their stock units. Existing rows retain their units,
conversion factors, sub-BOM links and operation assignments. ERPNext handles
validation, cost calculation, explosion and default BOM behavior. Concurrent
edits are rejected; submitted BOMs are read-only in this workspace. Advanced
configuration remains available through the explicit desktop link.

Implementation: `mobile_operations/bom.py`, `public/js/mobile_bom.js` and
`public/css/mobile_bom.css`. Run `bench build --app mobile_operations` after
installation to link assets and compile translations. Regression tests are
in `mobile_operations/test_bom.py`.
