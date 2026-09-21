import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// The offline shell, and the hook a notification arrives on. Registered after
// load so it never competes with the first paint.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.warn('service worker not registered:', err.message)
    })
  })

  // A worker taking over mid-visit means a newer app is on the server. Take it, but not
  // while somebody is looking at the screen: reload on the way out instead, so opening
  // the app again is what shows the new one. The guard on there having been a controller
  // before stops the first install from reloading the page under the reader.
  const handedOver = Boolean(navigator.serviceWorker.controller)
  let waiting = false

  const take = () => {
    if (document.visibilityState === 'hidden') window.location.reload()
    else waiting = true
  }

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (handedOver) take()
  })

  document.addEventListener('visibilitychange', () => {
    if (waiting && document.visibilityState === 'hidden') window.location.reload()
  })
}
