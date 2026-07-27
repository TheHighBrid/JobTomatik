import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            border: '1px solid #36537d',
            borderRadius: '14px',
            background: '#111a2e',
            color: '#f8fafc',
            boxShadow: '0 18px 55px rgba(0, 0, 0, 0.32)',
            fontSize: '14px',
          },
          success: {
            iconTheme: { primary: '#32c985', secondary: '#081220' },
          },
          error: {
            iconTheme: { primary: '#ff6574', secondary: '#081220' },
          },
        }}
      />
    </QueryClientProvider>
  </React.StrictMode>
)
