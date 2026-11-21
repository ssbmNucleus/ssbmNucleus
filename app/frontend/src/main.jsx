import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'
import { install as installErrorRing } from './shared/lib/errorRing'

// Capture renderer errors from the very start so bug reports can carry them.
installErrorRing()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
