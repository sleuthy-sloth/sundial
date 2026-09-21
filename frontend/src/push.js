/**
 * Turning a notification on, which is a conversation with three parties.
 *
 * The browser has to be asked for permission, the push service has to be given a
 * subscription, and sundial has to be told about it — and each can say no for its own
 * reason. Keeping the three steps here rather than in the panel is what lets the panel say
 * *which* step refused. "Could not turn on notifications" is the same sentence for a denied
 * permission, a browser that has no PushManager at all, and a server that rejected the
 * subscription, and the three need three different things done about them.
 *
 * Everything reaches the outside world through the `scope` argument, which defaults to the
 * real one. That is not ceremony: a test can then be the browser, and the interesting cases
 * here — permission refused, no service worker, a server that answers 400 — are exactly the
 * ones you cannot stage by hand on a phone.
 */

/** The server hands out base64url with the padding stripped; subscribe() wants bytes. */
export function keyBytes(base64) {
  // Padding is stripped before it is added back, so a key that arrives already padded is
  // read the same way as one that is not. The server sends it stripped; a hand-copied or
  // proxied key may not be, and `atob` refuses anything that is padded twice.
  const bare = String(base64).replace(/=+$/, '').replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(bare + '='.repeat((4 - (bare.length % 4)) % 4))
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

/**
 * What this browser can do, before anything is asked of anyone.
 *
 * `insecure` is its own answer because it is the one people hit without being told why:
 * push needs a secure origin, and a copy of sundial reached over plain http on the LAN
 * cannot have it, no matter what is clicked.
 */
export function availability(scope = globalThis) {
  const navigator = scope.navigator || {}
  if (!navigator.serviceWorker || !scope.Notification || !scope.PushManager) {
    return 'unsupported'
  }
  if (scope.isSecureContext === false) return 'insecure'
  if (scope.Notification.permission === 'denied') return 'denied'
  return 'ready'
}

/** What to tell a person about an answer they cannot act on by trying again. */
export function explain(state) {
  if (state === 'unsupported') {
    return 'This browser cannot be notified. On an iPhone, add sundial to your Home Screen first.'
  }
  if (state === 'insecure') return 'Notifications need a secure address (https).'
  if (state === 'denied') {
    return 'Notifications are turned off for sundial in your browser settings.'
  }
  return ''
}

/** The subscription this browser already has, or null. Used to render the on/off state. */
export async function current(scope = globalThis) {
  const registration = await scope.navigator?.serviceWorker?.ready
  const subscription = await registration?.pushManager?.getSubscription()
  return subscription || null
}

/**
 * Ask for permission, subscribe, and tell sundial.
 *
 * The order is the protocol rather than a preference: subscribing before permission is
 * granted is refused by the browser, and telling the server about a subscription the push
 * service never made would leave a dead row that the sender keeps trying.
 */
export async function enable(api, scope = globalThis) {
  const state = availability(scope)
  if (state !== 'ready') throw new Error(explain(state))

  const permission = await scope.Notification.requestPermission()
  if (permission !== 'granted') throw new Error(explain('denied'))

  const { public_key: publicKey } = await api.pushKey()
  const registration = await scope.navigator.serviceWorker.ready
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(publicKey),
  })

  await api.subscribePush(subscription.toJSON())
  return subscription
}

/**
 * Unsubscribe here, then say so there.
 *
 * This device first, deliberately. If the server call is what fails, the browser has
 * already stopped listening, which is the half the person can see — and the sender will
 * delete the row itself the first time the push service answers 410 for it.
 */
export async function disable(api, scope = globalThis) {
  const subscription = await current(scope)
  if (!subscription) return false

  const endpoint = subscription.endpoint
  await subscription.unsubscribe()
  await api.unsubscribePush(endpoint)
  return true
}
