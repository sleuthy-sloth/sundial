import { useEffect } from 'react'

import timelineLight from '../assets/empty-timeline-light.webp'
import timelineDark from '../assets/empty-timeline-dark.webp'
import inboxLight from '../assets/empty-inbox-light.webp'
import inboxDark from '../assets/empty-inbox-dark.webp'
import completeLight from '../assets/day-complete-light.webp'
import completeDark from '../assets/day-complete-dark.webp'

// Every derivative is 800x537 (see scripts/make_art.py), so the reserved box is stated once.
// The number matters: it is what stops the page jumping when a picture lands on a slow link.
const W = 800
const H = 537

const ART = {
  timeline: { light: timelineLight, dark: timelineDark, width: W, height: H },
  inbox: { light: inboxLight, dark: inboxDark, width: W, height: H },
  complete: { light: completeLight, dark: completeDark, width: W, height: H },
}

/**
 * A light and a dark file for the same picture, both in the DOM, with CSS showing the one that
 * matches the theme. Nothing is decided in JavaScript at paint time, so a dark-theme reader
 * never sees the light artwork flash past on the way in.
 *
 * Two details that are easy to get wrong:
 *
 *   * Both files carry their real width and height, so the box is the right shape before either
 *     arrives. Without that the page jumps when the picture lands, which on a slow connection
 *     is exactly when you would notice.
 *   * The artwork is hidden from assistive technology and has an empty alt. The words beside it
 *     are the state; a screen reader saying "illustration of a sundial" first would be noise.
 */
export default function LedgerArt({ kind, className = '' }) {
  const art = ART[kind]

  // Warm the other theme's file after first paint. Without this, flipping the theme swaps in an
  // unloaded image and the artwork pops in a moment later. ~25KB once, then cached.
  useEffect(() => {
    if (!art) return
    const other = document.documentElement.dataset.theme === 'dark' ? art.light : art.dark
    const warm = new Image()
    warm.src = other
  }, [art])

  if (!art) return null // no hook may come after this line

  // The empty timeline is the first thing on screen when it shows, so it is not lazy; the
  // others sit below the fold and can wait.
  const loading = kind === 'timeline' ? 'eager' : 'lazy'

  return (
    <div className={`art art-${kind} ${className}`.trim()} aria-hidden="true">
      <img
        className="art-light"
        src={art.light}
        width={art.width}
        height={art.height}
        alt=""
        loading={loading}
        decoding="async"
      />
      <img
        className="art-dark"
        src={art.dark}
        width={art.width}
        height={art.height}
        alt=""
        loading={loading}
        decoding="async"
      />
    </div>
  )
}
