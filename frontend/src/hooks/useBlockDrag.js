/** Moving a block with the pointer: a drag on the timeline, a drag on its bottom edge, and a
 *  drag out of the inbox onto an hour.
 *
 *  One pointer handler covers all three, because they are the same gesture with a different
 *  answer to "where does this land". What is being dragged is state rather than a listener
 *  per block, so a block that re-renders mid-drag does not lose the pointer.
 */

import { useEffect, useRef, useState } from 'react'
import { DAY_MIN, HOUR_PX, SNAP_MIN, snap } from '../time'

export function useBlockDrag({ day, write, contentRef, setSelectedId, setError }) {
  const [drag, setDrag] = useState(null)
  const [ghost, setGhost] = useState(null)
  const ghostRef = useRef(null) // mirrors `ghost` so pointerup reads the live value
  const movedRef = useRef(false)

  const setGhostValue = (g) => { ghostRef.current = g; setGhost(g) }

  const beginDrag = (e, mode, block) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = contentRef.current.getBoundingClientRect()
    const grabbedMin = ((e.clientY - rect.top) / HOUR_PX) * 60
    movedRef.current = false
    ghostRef.current = null
    setGhost(null)
    setSelectedId(block.id)
    setDrag({
      mode,
      id: block.id,
      title: block.title,
      duration: block.duration_min,
      start_min: block.start_min ?? 0,
      grabOffset: mode === 'move' ? grabbedMin - block.start_min : 0,
      originX: e.clientX,
      originY: e.clientY,
    })
  }

  useEffect(() => {
    if (!drag) return
    const onMove = (ev) => {
      const rect = contentRef.current?.getBoundingClientRect()
      if (!rect) return
      // Distance from the grab point, not movementX/Y: those are zero on the
      // first event and on some platforms, and a click must not read as a drag.
      const travelled = Math.hypot(ev.clientX - drag.originX, ev.clientY - drag.originY)
      movedRef.current = movedRef.current || travelled > 3
      const yMin = ((ev.clientY - rect.top) / HOUR_PX) * 60
      const inside =
        ev.clientY >= rect.top && ev.clientY <= rect.bottom &&
        ev.clientX >= rect.left && ev.clientX <= rect.right

      if (drag.mode === 'schedule') {
        if (!inside) {
          // Only draws a landing pad while the pointer is actually over the timeline.
          setGhostValue(null)
          return
        }
        // An item dropped near midnight takes the latest position it fits in, instead
        // of showing a landing pad that the API is going to refuse.
        const last = Math.max(0, DAY_MIN - drag.duration)
        setGhostValue({ start_min: Math.min(snap(yMin), last), duration_min: drag.duration })
      } else if (drag.mode === 'resize') {
        const stop = Math.min(Math.max(snap(yMin), drag.start_min + SNAP_MIN), DAY_MIN)
        setGhostValue({ start_min: drag.start_min, duration_min: stop - drag.start_min })
      } else {
        const max = DAY_MIN - drag.duration
        const start = Math.max(0, Math.min(max, snap(yMin - drag.grabOffset)))
        setGhostValue({ start_min: start, duration_min: drag.duration })
      }
    }

    const commit = async () => {
      const g = ghostRef.current
      const d = drag
      const moved = movedRef.current
      setDrag(null)
      setGhostValue(null)
      if (!g || !moved) return // a plain click selects, it does not reschedule
      try {
        if (d.mode === 'schedule') {
          await write(d.id, { day, start_min: g.start_min, duration_min: g.duration_min })
        } else {
          await write(d.id, { start_min: g.start_min, duration_min: g.duration_min })
        }
      } catch (e) {
        setError(e.message)
      }
    }

    // A cancelled gesture is not a drag that finished: the browser took the pointer
    // away (a system gesture, a phone call), so nothing was decided and nothing is
    // written. Treating it as a drop is how a block moved without being asked to.
    const abandon = () => {
      setDrag(null)
      setGhostValue(null)
      movedRef.current = false
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', commit)
    window.addEventListener('pointercancel', abandon)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', commit)
      window.removeEventListener('pointercancel', abandon)
    }
  }, [drag, day, write])

  return { drag, ghost, beginDrag }
}
