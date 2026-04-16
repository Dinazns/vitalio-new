/* VitalIO Service Worker - Push notifications */
self.addEventListener('push', (event) => {
  let payload = { title: 'VitalIO', body: 'Nouvelle alerte' }
  try {
    if (event.data) {
      payload = event.data.json()
    }
  } catch (e) {
    const text = event.data?.text?.()
    if (text) payload.body = text
  }
  const options = {
    body: payload.body || 'Nouvelle alerte patient',
    icon: '/favicon.ico',
    badge: '/favicon.ico',
    tag: payload.tag || 'vitalio-alert',
    data: { url: payload.url || '/' },
    requireInteraction: false,
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || 'VitalIO - Alerte', options)
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification?.data?.url || '/'
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(url)
          return client.focus()
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url)
      }
    })
  )
})
