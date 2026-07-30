const ROOM_ENTRY_RE = /^【窗边 · (\d{2})\/(\d{2}) (\d{2}):(\d{2})】$/u

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

export function buildRoomEntry(now: Date = new Date()): string {
  const date = `${pad2(now.getDate())}/${pad2(now.getMonth() + 1)}`
  const time = `${pad2(now.getHours())}:${pad2(now.getMinutes())}`
  return `【窗边 · ${date} ${time}】`
}

export function roomEntryTime(content: string): string {
  const match = content.trim().match(ROOM_ENTRY_RE)
  if (!match) return ''
  const day = Number(match[1])
  const month = Number(match[2])
  const hour = Number(match[3])
  const minute = Number(match[4])
  const daysInMonth = month >= 1 && month <= 12 ? new Date(2000, month, 0).getDate() : 0
  if (day < 1 || day > daysInMonth || hour > 23 || minute > 59) return ''
  return `${match[3]}:${match[4]}`
}

export function isRoomEntry(content: string): boolean {
  return Boolean(roomEntryTime(content))
}
