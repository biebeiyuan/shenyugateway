import { beforeEach, describe, expect, it } from 'vitest'
import { dedupeUiMessagesForRecovery, hasExactDuplicateRows } from '../src/session/history'
import { wireMessages } from '../src/api/client'
import { loadStoredMessages, persistStoredMessages } from '../src/session/persistence'
import { applyVariant, snapshotMessage } from '../src/session/variants'
import type { UiMessage } from '../src/types'

const event = { id: 'reply-one', event_at: '2026-09-18T08:00:00.000Z' }
function row(): UiMessage {
  return Object.assign({ id: 'display-slot', role: 'assistant' as const, content: '正文',
    echo: '私有', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [] },
    { archiveEvent: { ...event } })
}
beforeEach(() => localStorage.clear())
describe('archive event identity', () => {
  it('is sent separately from content and survives stripping display parts', () => {
    const source = row()
    expect(wireMessages([source])[0]).toHaveProperty('archive_event', event)
    source.echo = ''
    source.content = '\n\n正文'
    expect(wireMessages([source])[0]).toHaveProperty('archive_event', event)
  })
  it('survives local persistence, including selected roll variants', () => {
    const source = row()
    source.variants = [snapshotMessage(source)]
    persistStoredMessages([source], 75)
    expect(loadStoredMessages()[0]).toHaveProperty('archiveEvent', event)
  })
  it('moves with its roll variant instead of with the display slot', () => {
    const source = row()
    const first = snapshotMessage(source)
    const second = { ...first, archiveEvent: { ...event, id: 'reply-two' } }
    applyVariant(source, second, 1)
    expect(source).toHaveProperty('archiveEvent.id', 'reply-two')
    applyVariant(source, first, 0)
    expect(source).toHaveProperty('archiveEvent.id', 'reply-one')
  })
  it('does not invent identities or current timestamps for legacy restored history', () => {
    const source = row()
    delete (source as unknown as Record<string, unknown>).archiveEvent
    expect(wireMessages([source])[0]).not.toHaveProperty('archive_event')
    persistStoredMessages([source], 75)
    expect(loadStoredMessages()[0]).not.toHaveProperty('archiveEvent.id')
  })
})

it('defers incomplete replies without dropping their immutable identity', () => {
  const source = row()
  source.truncated = true
  expect(wireMessages([source])[0]).toHaveProperty('archive_pending', true)
  expect(wireMessages([source])[0]).toHaveProperty('archive_event', event)
  source.truncated = undefined
  expect(wireMessages([source])[0]).not.toHaveProperty('archive_pending')
})
it('keeps completion state with the selected roll, not the display slot', () => {
  const source = row()
  const complete = snapshotMessage(source)
  source.truncated = true
  const partial = snapshotMessage(source)
  applyVariant(source, complete, 0)
  expect(wireMessages([source])[0]).not.toHaveProperty('archive_pending')
  applyVariant(source, partial, 1)
  expect(wireMessages([source])[0]).toHaveProperty('archive_pending', true)
})


it('keeps equal text from distinct events during explicit history recovery', () => {
  const first = row()
  const second = { ...row(), archiveEvent: { ...event, id: 'another-turn' } }
  expect(hasExactDuplicateRows(wireMessages([first, second]))).toBe(false)
  expect(dedupeUiMessagesForRecovery([first, second])).toEqual([first, second])
})

it('recognizes the same event after private parts change during history recovery', () => {
  const first = row()
  const replay = { ...row(), content: '\n\n正文', echo: '' }
  expect(hasExactDuplicateRows(wireMessages([first, replay]))).toBe(true)
  expect(dedupeUiMessagesForRecovery([first, replay])).toEqual([first])
})

it('does not merge an identified event with equal legacy text during recovery', () => {
  const first = row()
  const legacy = { ...row(), archiveEvent: undefined }
  expect(hasExactDuplicateRows(wireMessages([first, legacy]))).toBe(false)
  expect(dedupeUiMessagesForRecovery([first, legacy])).toEqual([first, legacy])
})
