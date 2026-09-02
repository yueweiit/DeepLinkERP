import { lazy, useEffect } from 'react'
import { BrowserRouter, MemoryRouter, Navigate, Route, Routes } from 'react-router-dom'
import { FrappeProvider } from 'frappe-react-sdk'
import { Toaster } from '@/components/ui/sonner'
import BankReconciliation from '@/pages/BankReconciliation'
import BankStatementImporterContainer from '@/pages/BankStatementImporterContainer'
import { TooltipProvider } from './components/ui/tooltip'
import { LucideProvider } from 'lucide-react'
import { ThemeProvider } from './components/ui/theme-provider'

const BankStatementImporter = lazy(() => import('@/pages/BankStatementImporter'))
const ViewBankStatementImportLog = lazy(() => import('@/pages/ViewBankStatementImportLog'))

function App() {
	const isEmbedded = Boolean(window.__BANKING_ROOT__) ||
		new URLSearchParams(window.location.search).get('embedded') === '1'
	const currentUser = window.frappe?.boot?.user?.name || window.frappe?.session?.user || window.frappe?.boot?.user
	const routes = (
		<Routes>
			<Route index element={<BankReconciliation />} />
			<Route path="/statement-importer" element={<BankStatementImporterContainer />}>
				<Route index element={<BankStatementImporter />} />
				<Route path=":id" element={<ViewBankStatementImportLog />} />
			</Route>
			<Route path="*" element={<Navigate to="/" />} />
		</Routes>
	)
	useEffect(() => {
		if (isEmbedded) {
			return
		}
		// Check if user is logged in by checking the Cookie "user_id"
		// In Frappe, unauthenticated users are "Guest"
		const userId = document.cookie?.split('; ').find(row => row.startsWith('user_id='))?.split('=')[1]?.trim()
		const isLoggedIn = userId !== 'Guest'

		if (!isLoggedIn) {
			if (import.meta.env.DEV) {
				return
			}
			// Redirect to Frappe login page
			window.location.href = '/login?redirect-to=/banking'
			return
		}
	}, [isEmbedded])

	return (
		<LucideProvider
			strokeWidth={1.5}
		>
			<TooltipProvider>
				<FrappeProvider
					swrConfig={{
						errorRetryCount: 2
					}}
					socketPort={import.meta.env.VITE_SOCKET_PORT}
					siteName={window.frappe?.boot?.sitename ?? import.meta.env.VITE_SITE_NAME}>
					<ThemeProvider
						defaultTheme={window.frappe?.boot?.desk_theme ?? "Automatic"}
					>
						{(isEmbedded || (currentUser && currentUser !== 'Guest')) && (isEmbedded ?
							<MemoryRouter initialEntries={["/"]}>{routes}</MemoryRouter> :
							<BrowserRouter basename={import.meta.env.VITE_BASE_NAME ? `/${import.meta.env.VITE_BASE_NAME}` : ''}>{routes}</BrowserRouter>
						)}
						<Toaster richColors />
					</ThemeProvider>
				</FrappeProvider>
			</TooltipProvider>
		</LucideProvider>
	)
}

export default App
