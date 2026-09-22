/** The calendar, which is context layered beside the plan rather than part of it.
 *
 *  It keeps its own state for that reason: a calendar that will not load must leave the day
 *  exactly as it was, so nothing in here can set the plan's error or touch its blocks. The
 *  one place it reaches into the plan is to read the day's blocks, because an appointment and
 *  a block sharing an hour have to negotiate the column.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { appointments } from '../time'
import { syncNote } from '../calendar'
import { createLatest } from '../saving'

export function useCalendar({ tab, day, blocks }) {
  const [calendar, setCalendar] = useState(null)
  const [calendarDay, setCalendarDay] = useState({ day: null, events: [] })
  const [syncing, setSyncing] = useState(false)
  const [calendarNote, setCalendarNote] = useState('')
  const [connecting, setConnecting] = useState(false)
  const calendarLoad = useRef(createLatest())
  const askedToSync = useRef(false)

  const loadCalendar = useCallback(async (which) => {
    const ticket = calendarLoad.current.begin()
    try {
      const [status, events] = await Promise.all([api.calendars(), api.events(which)])
      if (!calendarLoad.current.isCurrent(ticket)) return
      setCalendar(status)
      setCalendarDay(events)
    } catch {
      // Context, not the plan: a calendar that will not read is not an error worth the
      // header. The panel says "not connected" or keeps the last good answer.
    }
  }, [])

  const runSync = useCallback(
    async (ifStaleSeconds = 0) => {
      setSyncing(true)
      try {
        const result = await api.syncCalendars(ifStaleSeconds)
        setCalendarNote(syncNote(result))
        await loadCalendar(day)
      } catch (e) {
        setCalendarNote(e.message)
      } finally {
        setSyncing(false)
      }
    },
    [day, loadCalendar],
  )

  useEffect(() => {
    if (tab !== 'day' && tab !== 'you') return
    loadCalendar(day)
  }, [tab, day, loadCalendar])

  /** Opening the day is the schedule. The server decides whether that means going
   *  to iCloud, so switching views never hammers it, and nothing runs in the background
   *  while the app is shut — a choice, explained in docs/calendar-sync.md.
   *
   *  Waits for the status before asking: syncing with nothing to sync with produces a
   *  refusal, and the rail would carry a filesystem path where a sentence belongs. */
  useEffect(() => {
    if (tab !== 'day' || !calendar?.configured || askedToSync.current) return
    askedToSync.current = true
    runSync(900)
  }, [tab, calendar, runSync])

  /** Typing a credential into the panel: the only secret this app is ever given.

   *  It goes straight to the server that writes the file, and the reply is the provider's
   *  state rather than an echo. Then it syncs — "is that password right?" is the only question
   *  anybody has at that moment, and nothing else can answer it. Returns a sentence when it
   *  did not work, so the panel can put it beside the fields.
   */
  const connectCalendar = useCallback(
    async (provider, fields) => {
      setConnecting(true)
      try {
        const state = await api.saveCredentials(provider, fields)
        setCalendarNote(state.why || 'Connected. Reading the calendar…')
        await loadCalendar(day)
        // The auto-sync above only ever runs once; connecting is a second reason to ask.
        // Deliberately not awaited: whether iCloud accepts the password is the sync's answer,
        // and the form should not sit there spinning while a server thinks about it.
        askedToSync.current = true
        runSync()
        return ''
      } catch (e) {
        return e.message
      } finally {
        setConnecting(false)
      }
    },
    [day, loadCalendar, runSync],
  )

  const toggleCalendar = useCallback(
    async (ref, enabled) => {
      try {
        await api.setCalendar(ref, enabled)
        await loadCalendar(day)
      } catch (e) {
        setCalendarNote(e.message)
      }
    },
    [day, loadCalendar],
  )

  // The calendar's own events, placed on the clock, and the blocks that have to make room for
  // them. Only for the day on screen: the panel's events belong to whichever day it last
  // fetched, and drawing yesterday's appointments onto today would be a quiet lie.
  const colourOf = useMemo(
    () => Object.fromEntries((calendar?.calendars ?? []).map((c) => [c.ref, c.colour])),
    [calendar],
  )
  const nameOf = useMemo(
    () => Object.fromEntries((calendar?.calendars ?? []).map((c) => [c.ref, c.name])),
    [calendar],
  )
  const inDay = useMemo(
    () => appointments(blocks, calendarDay.day === day ? calendarDay.events : [], day),
    [blocks, calendarDay, day],
  )

  return {
    calendar, calendarDay, syncing, note: calendarNote, connecting,
    loadCalendar, runSync, connectCalendar, toggleCalendar,
    colourOf, nameOf, inDay,
  }
}
