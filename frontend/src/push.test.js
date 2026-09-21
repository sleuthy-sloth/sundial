/** Unit tests for turning a notification on and off. Run: cd frontend && npm test
 *
 * The cases worth pinning are the refusals, because they are the ones you cannot stage by
 * hand: a browser with no PushManager, a permission that comes back "denied", and a server
 * that answers 400. Each has to reach the person as its own sentence, and each has to leave
 * nothing half-done behind it.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { availability, current, disable, enable, explain, keyBytes, testResultMessage } from './push.js'

/** A browser that says yes to everything, recording what it was asked. */
function scope(over = {}) {
  const calls = []
  const subscription = {
    endpoint: 'https://push.example/abc',
    toJSON: () => ({ endpoint: 'https://push.example/abc', keys: { p256dh: 'p', auth: 'a' } }),
    unsubscribe: async () => {
      calls.push(['unsubscribe'])
      return true
    },
  }
  const base = {
    isSecureContext: true,
    Notification: {
      permission: 'default',
      requestPermission: async () => {
        calls.push(['requestPermission'])
        return 'granted'
      },
    },
    PushManager: function PushManager() {},
    navigator: {
      serviceWorker: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: async () => null,
            subscribe: async (options) => {
              calls.push(['subscribe', options])
              return subscription
            },
          },
        }),
      },
    },
  }
  const merged = {
    ...base,
    ...over,
    Notification: { ...base.Notification, ...(over.Notification || {}) },
    navigator: { ...base.navigator, ...(over.navigator || {}) },
  }
  return { scope: merged, calls, subscription }
}

const fakeApi = (over = {}) => {
  const calls = []
  return {
    calls,
    api: {
      pushKey: async () => {
        calls.push(['pushKey'])
        return { public_key: 'BCCdny1zS2rkMA7u_4UgGip9', subscribers: 0 }
      },
      subscribePush: async (s) => {
        calls.push(['subscribePush', s])
        return { endpoint: s.endpoint, subscribers: 1 }
      },
      unsubscribePush: async (endpoint) => {
        calls.push(['unsubscribePush', endpoint])
        return { removed: true, subscribers: 0 }
      },
      ...over,
    },
  }
}

// --- the key ------------------------------------------------------------------

test('the key the server sends becomes the bytes subscribe() insists on', () => {
  const b64 = 'BCCdny1zS2rkMA7u_4UgGip9Xw'
  const expected = Uint8Array.from(
    Buffer.from(b64.replace(/-/g, '+').replace(/_/g, '/'), 'base64'),
  )
  assert.deepEqual(keyBytes(b64), expected)
})

test('base64url with the padding stripped decodes, and so does a padded key', () => {
  // The server strips padding; some browsers and older copies hand it back. Both must work,
  // and both must give the same bytes.
  const stripped = 'BCCdny1zS2rkMA7u_4UgGip9'
  assert.deepEqual(keyBytes(stripped), keyBytes(stripped + '==='))
})

// --- what the browser can do --------------------------------------------------

test('a browser with no service worker or no PushManager is unsupported, not broken', () => {
  assert.equal(availability({ Notification: {}, isSecureContext: true }), 'unsupported')
  assert.equal(
    availability({ navigator: { serviceWorker: {} }, isSecureContext: true }),
    'unsupported',
  )
})

test('plain http is its own answer, because that is the one nobody is told', () => {
  const { scope: s } = scope({ isSecureContext: false })
  assert.equal(availability(s), 'insecure')
})

test('a permission already refused is reported before anything is requested', () => {
  const { scope: s } = scope({ Notification: { permission: 'denied' } })
  assert.equal(availability(s), 'denied')
})

test('a granted or unasked permission is ready', () => {
  assert.equal(availability(scope({ Notification: { permission: 'granted' } }).scope), 'ready')
  assert.equal(availability(scope().scope), 'ready')
})

test('every refusal has a sentence, and being ready has none', () => {
  for (const state of ['unsupported', 'insecure', 'denied']) {
    assert.ok(explain(state).length > 10, `${state} needs something to show`)
  }
  assert.equal(explain('ready'), '')
})

test('the unsupported sentence names the thing to actually do about it', () => {
  assert.match(explain('unsupported'), /Home Screen/)
})

// --- turning it on ------------------------------------------------------------

test('enabling asks, subscribes against the server key, and tells the server', async () => {
  const { scope: s, calls } = scope()
  const { api, calls: apiCalls } = fakeApi()

  await enable(api, s)

  assert.deepEqual(calls.map((c) => c[0]), ['requestPermission', 'subscribe'])
  const options = calls[1][1]
  assert.equal(options.userVisibleOnly, true)
  assert.ok(options.applicationServerKey instanceof Uint8Array)
  assert.deepEqual(apiCalls.map((c) => c[0]), ['pushKey', 'subscribePush'])
  assert.equal(apiCalls[1][1].endpoint, 'https://push.example/abc')
})

test('a refused permission stops before subscribing and before telling the server', async () => {
  const { scope: s, calls } = scope({
    Notification: { requestPermission: async () => 'denied' },
  })
  const { api, calls: apiCalls } = fakeApi()

  await assert.rejects(() => enable(api, s), /browser settings/)

  // The override replaces the recording requestPermission, so `calls` empty is the claim:
  // a refused permission reaches neither the push service nor the server.
  assert.deepEqual(calls, [], 'nothing was subscribed')
  assert.deepEqual(apiCalls, [], 'a subscription that was never made is never announced')
})

test('an unsupported browser is refused without asking for anything', async () => {
  const { api, calls: apiCalls } = fakeApi()
  await assert.rejects(() => enable(api, { isSecureContext: true }), /Home Screen/)
  assert.deepEqual(apiCalls, [])
})

test('a server that refuses the subscription is surfaced, not swallowed', async () => {
  const { scope: s } = scope()
  const { api } = fakeApi({
    subscribePush: async () => {
      throw new Error('a subscription needs p256dh')
    },
  })
  await assert.rejects(() => enable(api, s), /p256dh/)
})

// --- turning it off -----------------------------------------------------------

test('disabling unsubscribes the device first, then tells the server', async () => {
  const { scope: s, calls } = scope({
    navigator: {
      serviceWorker: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: async () => ({
              endpoint: 'https://push.example/abc',
              unsubscribe: async () => {
                calls.push(['unsubscribe'])
                return true
              },
            }),
          },
        }),
      },
    },
  })
  const { api, calls: apiCalls } = fakeApi()

  assert.equal(await disable(api, s), true)
  assert.deepEqual(calls, [['unsubscribe']])
  assert.deepEqual(apiCalls, [['unsubscribePush', 'https://push.example/abc']])
})

test('disabling when nothing was subscribed does nothing and says so', async () => {
  const { scope: s } = scope()
  const { api, calls: apiCalls } = fakeApi()
  assert.equal(await disable(api, s), false)
  assert.deepEqual(apiCalls, [])
})

test('the current subscription is what renders the on/off state', async () => {
  const { scope: s } = scope()
  assert.equal(await current(s), null)
})

// ---- what "Send one now" comes back saying ------------------------------------------------
// A delivery failure and an empty subscriber list are different problems with different fixes,
// and the panel used to report the first as the second. Apple refused a perfectly good
// subscription with 403 BadJwtToken while the panel said "no device is subscribed", which sent
// the reader looking at their phone instead of at the subject claim.

test('a send that worked says so', () => {
  assert.match(testResultMessage({ subscribers: 1, sent: 1, failed: [] }), /^Sent\./)
})

test('a send with nobody subscribed names that, and not the delivery', () => {
  const said = testResultMessage({ subscribers: 0, sent: 0, failed: [] })
  assert.match(said, /No device is subscribed/)
})

test('a refusal from the push service is reported as a refusal, with the reason', () => {
  const said = testResultMessage({
    subscribers: 1,
    sent: 0,
    failed: [{ endpoint: 'https://push.example/x', error: 'WebPushException: 403 BadJwtToken' }],
  })
  assert.match(said, /refused/)
  assert.match(said, /BadJwtToken/, 'the reason is the whole value of the sentence')
  assert.doesNotMatch(said, /No device is subscribed/, 'a device WAS subscribed')
})

test('a refusal with no reason still does not blame the subscriber', () => {
  const said = testResultMessage({ subscribers: 1, sent: 0, failed: [{}] })
  assert.doesNotMatch(said, /No device is subscribed/)
  assert.match(said, /refused/)
})
