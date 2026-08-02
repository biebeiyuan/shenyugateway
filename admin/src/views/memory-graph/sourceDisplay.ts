// Shared display contract for recall sources on the memory-net pages.
// One home so the net view, the reading overlay, and future boards agree
// byte-for-byte on how each source is named, sealed, and paper-styled.

export type PaperFamily = 'letter' | 'sticky' | 'card' | 'slip' | 'plain'

export function sourceLabel(type: string): string {
  return ({
    journal: '日记',
    windowsill: '窗台',
    heartbeat: '心跳',
    room: '房间',
    board: '留言',
    memory: '旧记忆',
    calendar: '日历',
    mem_note: 'Mem',
    notebook: '笔记',
  } as Record<string, string>)[type] || type
}

export function sourceSeal(type: string): string {
  const seals: Record<string, string> = {
    journal: '记',
    windowsill: '窗',
    heartbeat: '跳',
    room: '房',
    board: '言',
    memory: '忆',
    calendar: '历',
    mem_note: 'M',
    notebook: '笔',
  }
  return seals[type] || sourceLabel(type).slice(0, 1) || '·'
}

/** Which kind of "paper" an original is rendered as in the reading overlay. */
export function paperFamily(type: string): PaperFamily {
  const families: Record<string, PaperFamily> = {
    journal: 'letter',
    mem_note: 'sticky',
    windowsill: 'card',
    board: 'card',
    heartbeat: 'slip',
  }
  return families[type] || 'plain'
}
