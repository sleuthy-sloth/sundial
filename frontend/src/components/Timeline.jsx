import { HOUR_PX, hhmm, durText, freeGaps } from '../time'
import Block from './Block'
import LedgerArt from './LedgerArt'

const HOURS = Array.from({ length: 24 }, (_, h) => h)

export default function Timeline({
  day, today, blocks, nowMin, selectedId, drag, ghost,
  appointments = [], squeezed, colourOf = {}, nameOf = {},
  contentRef, scrollerRef, onDoubleClick, onPointerDown, onSelect,
}) {
  const gaps = freeGaps(blocks)

  return (
    /* Focusable so a keyboard can scroll the day: a scrollable region with nothing focusable in
       it is unreachable without a mouse. It is a real tab stop, not a trap — Tab moves on. */
    <div
      className="scroller"
      ref={scrollerRef}
      tabIndex={0}
      role="group"
      aria-label="The day, hour by hour"
    >
      <div
        className="content"
        ref={contentRef}
        onDoubleClick={onDoubleClick}
        title="Double-click to add a block"
      >
        {HOURS.map((h) => (
          <div key={h} className="hour" style={{ top: h * HOUR_PX }}>
            {/* a ruler, not a wall of numbers: every other hour is named */}
            {h % 2 === 0 && <span className="hour-label">{hhmm(h * 60)}</span>}
          </div>
        ))}

        {gaps.map((g) => (
          <div
            key={`gap-${g.start_min}`}
            className="gap"
            style={{ top: (g.start_min / 60) * HOUR_PX, height: (g.minutes / 60) * HOUR_PX }}
          >
            <span>{durText(g.minutes)} open</span>
          </div>
        ))}

        {day === today && (
          <div className="now" style={{ top: (nowMin / 60) * HOUR_PX }}>
            <span className="now-chip">{hhmm(nowMin)}</span>
          </div>
        )}

        {/* The calendar's own events, drawn under the plan: an appointment is readable in full
            ink and is not yours to move, and those two things are said separately — full-ink type
            for the first, a dotted hairline and a default cursor for the second. Painting them
            before the blocks keeps a block on top wherever they share an edge. */}
        {appointments.map((a) => {
          const height = Math.max((a.minutes / 60) * HOUR_PX - 4, 18)
          return (
            <div
              key={a.key}
              className={`appt c-${colourOf[a.calendar_ref] ?? 'slate'}${a.clash ? ' clash' : ''}`}
              data-event={a.id}
              data-calendar={a.calendar_ref}
              style={{
                top: (a.start_min / 60) * HOUR_PX,
                height,
                '--lane': a.lane,
                '--lanes': a.lanes,
              }}
              title={`${a.title} — from ${nameOf[a.calendar_ref] ?? 'a calendar'}`}
            >
              <span className="appt-time">{hhmm(a.start_min)}</span>
              <span className="appt-title">{a.title}</span>
              <span className="appt-cal">{nameOf[a.calendar_ref] ?? ''}</span>
            </div>
          )
        })}

        {blocks.map((b) => {
          const live = drag?.id === b.id && drag.mode !== 'schedule' && ghost
          const isNow =
            day === today && b.start_min <= nowMin && nowMin < b.start_min + b.duration_min
          return (
            <Block
              key={b.id}
              block={b}
              view={live ? ghost : null}
              isNow={isNow}
              clash={Boolean(squeezed?.has(b.id))}
              selected={selectedId === b.id}
              onPointerDown={onPointerDown}
              onSelect={onSelect}
            />
          )
        })}

        {drag?.mode === 'schedule' && ghost && (
          <div
            className="block ghost"
            style={{
              top: (ghost.start_min / 60) * HOUR_PX,
              height: (ghost.duration_min / 60) * HOUR_PX,
            }}
          >
            <span className="block-time">{hhmm(ghost.start_min)}</span>
            <span className="block-title">{drag.title}</span>
          </div>
        )}

        {blocks.length === 0 && (
          <div className="state state-timeline">
            <LedgerArt kind="timeline" />
            <p className="timeline-empty">
              Nothing planned yet — double-click a time, or drag something over from the inbox.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
