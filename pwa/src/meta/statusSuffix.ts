import { fetchWeather, type RequestContext } from '../api/client'
import { companionDay } from './days'

// 用户消息尾部的状态后缀（跨端契约第1条）：
// 【{DD}/{MM} 周{W} {HH}:{mm} · 第{N}天 · 🔋{P}%⚡ · {城市} {天气} {温度}℃】
// 时间与第N天两段永远存在；电量、天气两段各自可缺省。
// 快照的采集（电池事件、天气轮询）全部在后台维护，绝不阻塞发消息路径。

export type BatterySnapshot = { level: number; charging: boolean }
export type WeatherSnapshot = { city: string; text: string; tempC: number | null }

export type StatusParts = {
  now?: Date
  battery?: BatterySnapshot | null
  weather?: WeatherSnapshot | null
}

// 与 Python 侧识别正则同义（跨端契约，尾部锚定）。
const STATUS_SUFFIX_RE = /\s*【\d{1,2}\/\d{1,2}\s*周[一二三四五六日]\s*\d{1,2}:\d{2}[^【】]*】\s*$/u

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const WEATHER_REFRESH_MS = 15 * 60 * 1000
const WEATHER_STALE_MS = 45 * 60 * 1000

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

export function buildStatusSuffix(parts: StatusParts = {}): string {
  const now = parts.now ?? new Date()
  const battery = parts.battery !== undefined ? parts.battery : batterySnapshot
  const weather = parts.weather !== undefined ? parts.weather : freshWeather(now.getTime())
  const segments = [
    `${pad2(now.getDate())}/${pad2(now.getMonth() + 1)} 周${WEEKDAYS[now.getDay()]} ${pad2(now.getHours())}:${pad2(now.getMinutes())}`,
    `第${companionDay(now)}天`,
  ]
  if (battery && Number.isFinite(battery.level)) {
    segments.push(`🔋${Math.round(battery.level * 100)}%${battery.charging ? '⚡' : ''}`)
  }
  if (weather && weather.city && weather.text) {
    const temp = weather.tempC !== null && Number.isFinite(weather.tempC) ? ` ${Math.round(weather.tempC)}℃` : ''
    segments.push(`${weather.city} ${weather.text}${temp}`)
  }
  return `【${segments.join(' · ')}】`
}

// 幂等：循环剥除，历史上误叠加的多层后缀也能一次清干净。
export function stripStatusSuffix(text: string): string {
  let result = text
  while (STATUS_SUFFIX_RE.test(result)) {
    result = result.replace(STATUS_SUFFIX_RE, '')
  }
  return result
}

// 先剥旧后缀再追加新后缀——编辑重发时旧状态被换新，不叠加。
export function stampStatusSuffix(text: string, parts: StatusParts = {}): string {
  const body = stripStatusSuffix(text)
  const suffix = buildStatusSuffix(parts)
  return body ? `${body} ${suffix}` : suffix
}

// 渲染层切分：气泡正文与尾部状态后缀分开展示，与消息数据无关。
export function splitStatusSuffix(text: string): { body: string; suffix: string } {
  const match = text.match(STATUS_SUFFIX_RE)
  if (!match || match.index === undefined) return { body: text, suffix: '' }
  return { body: text.slice(0, match.index).replace(/\s+$/u, ''), suffix: match[0].trim() }
}

// ---- 电池快照 ---------------------------------------------------------------

type BatteryManagerLike = {
  level: number
  charging: boolean
  addEventListener: (type: string, listener: () => void) => void
}

let batterySnapshot: BatterySnapshot | null = null
let batteryWatchStarted = false

export function initBatteryWatch() {
  if (batteryWatchStarted) return
  batteryWatchStarted = true
  const nav = navigator as Navigator & { getBattery?: () => Promise<BatteryManagerLike> }
  if (typeof nav.getBattery !== 'function') return
  nav.getBattery().then((battery) => {
    const update = () => {
      batterySnapshot = { level: Number(battery.level), charging: Boolean(battery.charging) }
    }
    update()
    battery.addEventListener('levelchange', update)
    battery.addEventListener('chargingchange', update)
  }).catch(() => {
    batterySnapshot = null
  })
}

// ---- 天气快照 ---------------------------------------------------------------

let weatherSnapshot: (WeatherSnapshot & { fetchedAt: number }) | null = null
let weatherWatchStarted = false
let weatherInFlight = false
let weatherContext: (() => RequestContext) | null = null

function freshWeather(atMs: number): WeatherSnapshot | null {
  if (!weatherSnapshot) return null
  return atMs - weatherSnapshot.fetchedAt <= WEATHER_STALE_MS ? weatherSnapshot : null
}

async function refreshWeather() {
  if (!weatherContext || weatherInFlight) return
  weatherInFlight = true
  try {
    const payload = await fetchWeather(weatherContext())
    // typeof 检查而非 Number() 强转：Number(null)===0 会伪造出 0℃。
    const tempC = typeof payload.temp_c === 'number' && Number.isFinite(payload.temp_c) ? payload.temp_c : null
    if (payload.available === true && payload.city && payload.text) {
      weatherSnapshot = { city: String(payload.city), text: String(payload.text), tempC, fetchedAt: Date.now() }
    }
  } catch {
    // 天气拿不到就沿用上一份快照（过期自然缺省），失败静默。
  } finally {
    weatherInFlight = false
  }
}

export function initWeatherWatch(getContext: () => RequestContext) {
  weatherContext = getContext
  void refreshWeather()
  if (weatherWatchStarted) return
  weatherWatchStarted = true
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void refreshWeather()
  })
  window.setInterval(() => { void refreshWeather() }, WEATHER_REFRESH_MS)
}
