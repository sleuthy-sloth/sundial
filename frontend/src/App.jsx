/** The shell: which destination you are in, the theme, and the composition of the screens.
 *
 * The state behind them lives in the hooks — the plan in `usePlanner`, the calendar in
 * `useCalendar`, the pointer in `useBlockDrag`, the clock in `usePlannerClock`. What is left
 * here is what App.jsx is for: the refs the DOM hands back, and which component goes where.
 *
 * The `CalendarPanel` import that used to sit here did not: App imported it and never rendered
 * it — the profile tab is what draws the panel — so the bundler was carrying a component for
 * nobody. The panel itself is untouched, and Profile still uses it.
 */

import { useEffect, useRef, useState } from 'react'
import { DAY_MIN, HOUR_PX, busyMinutes, durText, hhmm, shiftDay, todayISO } from './time'
import { dayIsClear } from './art'
import { applyTheme, initialTheme, rememberTheme } from './theme'
import { usePlanner } from './hooks/usePlanner'
import { useCalendar } from './hooks/useCalendar'
import { useBlockDrag } from './hooks/useBlockDrag'
import { usePlannerClock } from './hooks/usePlannerClock'
import Header from './components/Header'
import Inbox from './components/Inbox'
import Timeline from './components/Timeline'
import Editor from './components/Editor'
import Agenda from './components/Agenda'
import Glance from './components/Glance'
import TabBar from './components/TabBar'
import Profile from './components/Profile'

const VIEW_KEY = 'sundial-view'
const TABS = ['today', 'day', 'you']

export default function App() {
  // Where you are: the plan, the clock, or the app's own settings — the three destinations the
  // tab bar offers, and the same three at every width. The old names are read once so a browser
  // that remembered them lands somewhere sensible instead of nowhere.
  const [tab, setTab] = useState(() => {
    const remembered = localStorage.getItem(VIEW_KEY)
    if (TABS.includes(remembered)) return remembered
    if (remembered === 'todo') return 'today'
    if (remembered === 'calendar') return 'day'
    return 'today'
  })
  const [theme, setTheme] = useState(initialTheme)

  const contentRef = useRef(null)
  const scrollerRef = useRef(null)
  const captureRef = useRef(null)

  const nowMin = usePlannerClock()
  const {
    day, setDay, today, blocks, inbox, routines, selectedId, subject,
    open, openRoutine, close, draft, setDraft, error, setError, leaving, settling,
    write, capture, addToSection, scheduleAt, toggleDone, editor,
  } = usePlanner({ contentRef })
  const {
    calendar, calendarDay, syncing, note, connecting,
    runSync, connectCalendar, toggleCalendar, colourOf, nameOf, inDay,
  } = useCalendar({ tab, day, blocks })
  const { drag, ghost, beginDrag } = useBlockDrag({
    day, write, contentRef, setSelectedId: open, setError,
  })

  useEffect(() => { applyTheme(theme) }, [theme])
  useEffect(() => { localStorage.setItem(VIEW_KEY, tab) }, [tab])

  // Land somewhere useful: half an hour before now, else 7am.
  useEffect(() => {
    if (!scrollerRef.current) return
    const focusMin = day === todayISO() ? nowMin - 30 : 7 * 60
    scrollerRef.current.scrollTop = Math.max(0, (focusMin / 60) * HOUR_PX - 60)
  }, [day, tab]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    rememberTheme(next)
    setTheme(next)
  }

  // Time spoken for, not the sum of the durations: a block nested inside another is
  // not two hours of your day, and "open" has to mean open.
  const planned = busyMinutes(blocks)
  const layout = ['layout']
  if (tab === 'day') layout.push('with-rail')
  if (subject) layout.push('with-editor')

  return (
    <div className={layout.join(' ')}>
      {tab === 'day' && (
        <aside className="side">
          {/* Above 780px only, and only on the clock: the inbox is a drag source, and a drag
              needs somewhere to land. On a phone the same tasks are in Today. */}
          <h1 className="brand">sundial</h1>
          <Inbox
            items={inbox}
            draft={draft}
            selectedId={selectedId}
            onDraft={setDraft}
            onCapture={capture}
            onPointerDown={beginDrag}
            onSelect={open}
          />
        </aside>
      )}

      <main className="day">
        <Header
          day={day}
          today={today}
          clock={hhmm(nowMin)}
          tally={`${durText(planned)} planned · ${durText(Math.max(DAY_MIN - planned, 0))} open`}
          theme={theme}
          error={error}
          onPickDay={setDay}
          onShift={(delta) => setDay(shiftDay(day, delta))}
                    onTheme={toggleTheme}
        />

        {tab === 'today' && (
          <div className="view">
            {/* The glance sits above the plan rather than inside it: what is happening now is a
                fact about the day, and the agenda below is the list of what is left. */}
            <Glance blocks={blocks} day={day} today={today} nowMin={nowMin} />
            <Agenda
              blocks={blocks}
              inbox={inbox}
              draft={draft}
              captureRef={captureRef}
              onDraft={setDraft}
              onCapture={capture}
              onOpen={open}
              onToggle={toggleDone}
              onAddAt={addToSection}
              leaving={leaving}
              settling={settling}
              dayClear={dayIsClear(blocks, inbox, day, today)}
            />
          </div>
        )}

        {tab === 'day' && (
          <div className="view is-timeline">
            <Timeline
              day={day}
              today={today}
              blocks={blocks}
              nowMin={nowMin}
              selectedId={selectedId}
              drag={drag}
              ghost={ghost}
              appointments={inDay.spans}
              squeezed={inDay.squeezed}
              colourOf={colourOf}
              nameOf={nameOf}
              contentRef={contentRef}
              scrollerRef={scrollerRef}
              onDoubleClick={scheduleAt}
              onPointerDown={beginDrag}
              onSelect={open}
            />
          </div>
        )}

        {tab === 'you' && (
          <div className="view">
            <Profile
              status={calendar}
              events={calendarDay.events}
              busy={syncing}
              note={note}
              onSync={runSync}
              onToggle={toggleCalendar}
              onConnect={connectCalendar}
              connecting={connecting}
              theme={theme}
              onTheme={toggleTheme}
              routines={routines}
              onOpenRoutine={openRoutine}
            />
          </div>
        )}
      </main>

      <TabBar tab={tab} onTab={setTab} />

      {subject && (
        <Editor
          /* Keyed on the subject, not on the id: switching between a day and its rule is a
             different thing to edit, and the panel should arrive with that thing's values in
             its fields rather than the other's half-typed draft. */
          key={`${subject.kind}:${(subject.block ?? subject.routine).id}`}
          subject={subject}
          day={day}
          {...editor}
          onClose={close}
        />
      )}

    </div>
  )
}
