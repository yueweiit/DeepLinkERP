# Mobile Operations

Mobile-first warehouse and manufacturing operation pages for ERPNext.

## Mobile entry

Open `/mobile` on a phone. Unauthenticated users are sent to `/mobile/login`,
which uses the standard Frappe login endpoint and session cookie. The mobile
shell keeps its own routes for material requests, inventory, stock movement,
and production; desktop Desk is only opened through an explicit
`电脑端处理` action.
