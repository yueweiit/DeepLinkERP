import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import './lib/namespace'
import { DirectionProvider } from './components/ui/direction.tsx'

const bankingRoot = window.__BANKING_ROOT__ || document.getElementById('root')

function mountBankingApp(layoutDirection: string) {
	if (!bankingRoot) {
		console.error('Banking root element was not found')
		return
	}

	if (window.frappe?.model?.sync && window.frappe?.boot?.docs) {
		window.frappe.model.sync(window.frappe.boot.docs)
	}

	createRoot(bankingRoot).render(
		<StrictMode>
			<DirectionProvider dir={layoutDirection}>
				<App />
			</DirectionProvider>
		</StrictMode>,
	)
}

if (import.meta.env.DEV) {
  fetch('/api/method/erpnext.www.banking.get_context_for_dev', {
    method: 'POST',
  }).then(response => response.json()).then((values) => {
    if (!window.frappe) window.frappe = {};
    //@ts-expect-error - frappe will be available
    frappe.boot = JSON.parse(values.message.boot);
    //@ts-expect-error - frappe will be available
    frappe._messages = frappe.boot["__messages"];

    // Set document direction to rtl
    document.dir = values.message.layout_direction;
    //@ts-expect-error - frappe will be available
    mountBankingApp(values.message.layout_direction)

  })
} else {
  //@ts-expect-error - frappe will be available
  mountBankingApp(window.frappe?.boot?.layout_direction ?? 'ltr')
}
