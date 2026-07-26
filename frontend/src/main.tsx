import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { PeriodProvider } from './period/PeriodContext'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <PeriodProvider>
        <App />
      </PeriodProvider>
    </BrowserRouter>
  </StrictMode>,
)
