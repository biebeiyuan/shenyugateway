// 第N天：第1天 = 2026-03-09（Asia/Shanghai 自然日），跳天发生在北京时间 0 点。
// 跨端契约参考实现——pwa 与 admin 各持一份，逻辑必须逐字等价，不要单侧改动。
export const DAY_ONE_UTC = Date.UTC(2026, 2, 9)

export function companionDay(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  const [y, m, d] = parts.split('-').map(Number)
  return Math.floor((Date.UTC(y, m - 1, d) - DAY_ONE_UTC) / 86400000) + 1
}
