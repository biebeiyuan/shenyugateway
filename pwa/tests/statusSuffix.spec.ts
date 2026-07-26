import { describe, expect, it } from 'vitest'
import { companionDay } from '../src/meta/days'
import { buildStatusSuffix, splitStatusSuffix, stampStatusSuffix, stripStatusSuffix } from '../src/meta/statusSuffix'

// 跨端契约第1条的 JS 识别正则，逐字复刻，验证拼装与识别互相咬合。
const CONTRACT_RE = /\s*【\d{1,2}\/\d{1,2}\s*周[一二三四五六日]\s*\d{1,2}:\d{2}[^【】]*】\s*$/u

// Local-clock fixture: 2026-07-26 14:05 on the device, whatever its timezone.
// The day count is derived through companionDay on the same instant, so the
// expectation stays timezone independent.
const fixedNow = () => new Date(2026, 6, 26, 14, 5)

describe('buildStatusSuffix', () => {
  it('always carries zero-padded time and the companion day', () => {
    const suffix = buildStatusSuffix({ now: fixedNow(), battery: null, weather: null })
    expect(suffix).toBe(`【26/07 周日 14:05 · 第${companionDay(fixedNow())}天】`)
  })

  it('zero-pads single-digit day, month, hour and minute', () => {
    const now = new Date(2026, 2, 9, 8, 5)
    const suffix = buildStatusSuffix({ now, battery: null, weather: null })
    expect(suffix.startsWith('【09/03 周一 08:05 · ')).toBe(true)
  })

  it('appends the battery segment with a bolt only while charging', () => {
    const charging = buildStatusSuffix({ now: fixedNow(), battery: { level: 0.87, charging: true }, weather: null })
    expect(charging).toContain(' · 🔋87%⚡】')
    const draining = buildStatusSuffix({ now: fixedNow(), battery: { level: 0.87, charging: false }, weather: null })
    expect(draining).toContain(' · 🔋87%】')
    expect(draining).not.toContain('⚡')
  })

  it('appends the weather segment with an integer temperature', () => {
    const suffix = buildStatusSuffix({ now: fixedNow(), battery: null, weather: { city: '邵阳', text: '霾', tempC: 25.6 } })
    expect(suffix).toContain(' · 邵阳 霾 26°C】')
  })

  it('keeps city and condition but omits the temperature when tempC is null', () => {
    const suffix = buildStatusSuffix({ now: fixedNow(), battery: null, weather: { city: '邵阳', text: '霾', tempC: null } })
    expect(suffix).toContain(' · 邵阳 霾】')
    expect(suffix).not.toContain('°C')
    expect(CONTRACT_RE.test(suffix)).toBe(true)
  })

  it('omits optional segments independently and matches the contract regex', () => {
    const timeOnly = buildStatusSuffix({ now: fixedNow(), battery: null, weather: null })
    expect(timeOnly).not.toContain('🔋')
    expect(timeOnly).not.toContain('°C')
    const full = buildStatusSuffix({ now: fixedNow(), battery: { level: 1, charging: true }, weather: { city: '邵阳', text: '晴', tempC: 30 } })
    for (const suffix of [timeOnly, full]) {
      expect(CONTRACT_RE.test(suffix)).toBe(true)
    }
  })
})

describe('stripStatusSuffix', () => {
  it('strips a stamped suffix cleanly and stays idempotent', () => {
    const stamped = stampStatusSuffix('你好呀', { now: fixedNow(), battery: { level: 0.5, charging: false }, weather: { city: '邵阳', text: '霾', tempC: 25 } })
    expect(stripStatusSuffix(stamped)).toBe('你好呀')
    expect(stripStatusSuffix(stripStatusSuffix(stamped))).toBe('你好呀')
    expect(stripStatusSuffix('你好呀')).toBe('你好呀')
  })

  it('does not stack when restamping already stamped text', () => {
    const first = stampStatusSuffix('正文', { now: fixedNow(), battery: null, weather: null })
    const second = stampStatusSuffix(first, { now: new Date(2026, 6, 26, 15, 30), battery: null, weather: null })
    expect(second.match(/【/gu)).toHaveLength(1)
    expect(second).toContain('15:30')
    expect(stripStatusSuffix(second)).toBe('正文')
  })

  it('removes legacy double-stacked suffixes in one call', () => {
    const one = buildStatusSuffix({ now: fixedNow(), battery: null, weather: null })
    const two = buildStatusSuffix({ now: new Date(2026, 6, 25, 9, 1), battery: null, weather: null })
    expect(stripStatusSuffix(`正文 ${two} ${one}`)).toBe('正文')
  })

  it('keeps interior brackets that are not a status suffix', () => {
    expect(stripStatusSuffix('看看【这本书】怎么样')).toBe('看看【这本书】怎么样')
    expect(stripStatusSuffix('【只是个括号】')).toBe('【只是个括号】')
  })

  it('stamps an empty body (image-only message) as the bare suffix', () => {
    const stamped = stampStatusSuffix('', { now: fixedNow(), battery: null, weather: null })
    expect(stamped.startsWith('【')).toBe(true)
    expect(stripStatusSuffix(stamped)).toBe('')
  })
})

describe('splitStatusSuffix', () => {
  it('separates body and suffix for rendering', () => {
    const stamped = stampStatusSuffix('晚上吃什么', { now: fixedNow(), battery: { level: 0.4, charging: true }, weather: null })
    const { body, suffix } = splitStatusSuffix(stamped)
    expect(body).toBe('晚上吃什么')
    expect(suffix.startsWith('【26/07')).toBe(true)
    expect(suffix.endsWith('】')).toBe(true)
  })

  it('returns the whole text as body when there is no suffix', () => {
    expect(splitStatusSuffix('普通消息')).toEqual({ body: '普通消息', suffix: '' })
  })
})
