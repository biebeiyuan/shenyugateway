import { describe, expect, it } from 'vitest'
import { buildRoomEntry, isRoomEntry, roomEntryTime } from '../src/meta/roomEntry'

describe('Room entry contract', () => {
  it('builds the exact timestamped entry from the device clock', () => {
    const entry = buildRoomEntry(new Date(2026, 6, 27, 21, 0))
    expect(entry).toBe('【窗边 · 27/07 21:00】')
    expect(roomEntryTime(entry)).toBe('21:00')
  })

  it('recognizes only the complete new entry shape', () => {
    expect(isRoomEntry('【窗边 · 03/11 08:05】')).toBe(true)
    expect(isRoomEntry('  【窗边 · 03/11 08:05】  ')).toBe(true)
    expect(isRoomEntry('<proxy_sender name="沈予"/>——窗边')).toBe(false)
    expect(isRoomEntry('[窗边 · 03/11 08:05]')).toBe(false)
    expect(isRoomEntry('【窗边 · 3/11 08:05】')).toBe(false)
    expect(isRoomEntry('【窗边 · 32/11 08:05】')).toBe(false)
    expect(isRoomEntry('【窗边 · 03/11 24:05】')).toBe(false)
    expect(isRoomEntry('想去窗边坐坐')).toBe(false)
  })

  it('does not invent a reply label for ordinary messages', () => {
    expect(roomEntryTime('普通消息')).toBe('')
  })
})
