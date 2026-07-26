import { describe, expect, it } from 'vitest'
import { companionDay } from '../src/meta/days'

// All fixtures are absolute instants (explicit +08:00 offset), so the assertions
// hold no matter which timezone the test runner uses.

describe('companionDay', () => {
  it('anchors day one to 2026-03-09 in Asia/Shanghai', () => {
    expect(companionDay(new Date('2026-03-09T00:30:00+08:00'))).toBe(1)
    expect(companionDay(new Date('2026-03-09T23:59:00+08:00'))).toBe(1)
  })

  it('matches the calibration point: 2026-07-26 is day 140', () => {
    expect(companionDay(new Date('2026-07-26T12:00:00+08:00'))).toBe(140)
  })

  it('rolls over at Beijing midnight, not at 8am', () => {
    expect(companionDay(new Date('2026-07-25T23:59:00+08:00'))).toBe(139)
    expect(companionDay(new Date('2026-07-26T00:01:00+08:00'))).toBe(140)
    // The old implementation only advanced at 8am Beijing time.
    expect(companionDay(new Date('2026-07-26T07:59:00+08:00'))).toBe(140)
  })

  it('counts a Shanghai day even when the UTC date is still the day before', () => {
    // 2026-07-26T01:00+08:00 is 2026-07-25T17:00Z.
    expect(companionDay(new Date('2026-07-26T01:00:00+08:00'))).toBe(140)
  })
})
