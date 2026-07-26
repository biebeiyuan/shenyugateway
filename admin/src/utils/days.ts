// 第1天 = 2026-03-09（Asia/Shanghai 自然日）；跳天在北京时间 0 点。
// 与 pwa 的 companionDay 逐字等价，改动必须两边同步。
const DAY_ONE_UTC = Date.UTC(2026, 2, 9)

export function companionDay(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  const [y, m, d] = parts.split('-').map(Number)
  return Math.floor((Date.UTC(y, m - 1, d) - DAY_ONE_UTC) / 86400000) + 1
}
