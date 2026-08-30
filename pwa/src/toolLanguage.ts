export type ToolEvent = {
  phase: string
  tool_call_id: string
  name: string
  target_tool?: string
  round?: number
  cached?: boolean
  duration_ms?: number
  ok?: boolean | null
  error_kind?: string
  input?: unknown
  output?: string
  text_offset?: number
  stream_order?: number
}

export function toolName(event: ToolEvent): string {
  return String(event.target_tool || event.name || 'gateway_tool').replace(/^shenyu_/, '')
}

// 沈予做了什么，用他自己的说法。
//
// 按**完整工具名**精确匹配，不再用 includes 逐条试——原先那样会把
// search_mem_notes 说成「在窗台写了点东西」（它含 note，先撞上写那条），
// 把 delete_mem_note 也说成写，还把房间里每一扇门糊成同一句「在窗台看了看」。
// 读、写、删是三件不同的事；抱抱枕和开抽屉也是。
//
// 措辞的分寸：他在自己家里做事，所以是「翻了翻」「记下」这种平常动作，
// 不是「执行查询」；也不说「我可以」——那含请求许可的意思，这些门本来就是他的。
const EXACT_COPY: Record<string, string> = {
  // 便签：找 / 写 / 改 / 撕
  search_mem_notes: '翻了翻便签',
  list_mem_notes: '翻了翻便签',
  write_mem_note: '记下一张便签',
  update_mem_note: '改了改那张便签',
  bulk_update_mem_notes: '整理了一批便签',
  delete_mem_note: '撕掉了一张便签',

  // 回忆
  recall: '想起了一些事',
  recall_read: '把那段翻出来看了',
  recall_main_thread: '回头看了看主线',
  ask_memory: '想起了一些事',
  surface_passages: '想起了一些事',
  search_primary_texts: '翻了翻原文',
  get_meta_summaries: '回头看了看脉络',
  last_seen: '看了看上次是什么时候',

  // 星星
  create_star: '点亮了一颗星',
  search_stars: '在星图上找了找',
  list_stars: '看了看星图',
  star_review: '把星星过了一遍',
  star_feedback: '给星星记了一笔',
  connect_constellation: '把几颗星连了起来',
  merge_stars: '把几颗星并成一颗',
  archive_star: '把那颗星收起来了',
  mark_constant: '把那颗星留成常亮的',

  // 日历与心跳
  add_calendar: '在日历上写了一笔',
  read_heartbeat: '听了听心跳',

  // 窗台
  windowsill_write: '在窗台写了点东西',
  windowsill_list: '回窗台翻了翻',

  // 手边的本子
  notebook_write: '在本子上写了几行',
  notebook_list: '翻了翻手边的本子',
  notebook_update: '改了改本子上那几行',

  // 相册
  album_save: '把这张存进了相册',
  album_list: '翻了翻相册',

  // 书架与来历书
  books: '翻了翻书架',
  conflict_list: '看了看架上的来历书',
  conflict_read: '翻开了一本来历书',
  conflict_annotate: '在来历书上添了一句',

  // 窗外
  web_search: '往窗外看了看',
  web_read: '把那页带回来读了',

  // 房间里的门——每一扇都有自己的动作
  room_sit_by_window: '在窗边坐了一会儿',
  room_newspaper_basket: '翻了翻旧报纸',
  room_scribble: '在窗台上写了几笔',
  room_notebook: '翻了翻那本乱本子',
  room_wooden_box: '打开了装心跳的木盒',
  room_drawer_notes: '看了圆圆留的条子',
  room_locked_drawer: '开了那只上锁的抽屉',
  room_star_map: '在星图前站了一会儿',
  room_wall_pins: '看了看墙上钉着的',
  room_octopus_pillow: '抱了抱章鱼枕头',
  room_conflict_shelf: '看了看那排来历书',
}

// 兜底靠前缀。精确表没命中时（新工具、supabase_*、mcp_*）至少说对大类。
const PREFIX_COPY: [string, string][] = [
  ['web', '往窗外看了看'],
  ['album', '翻了翻相册'],
  ['star', '拨了拨星星'],
  ['note', '翻了翻便签'],
  ['recall', '想起了一些事'],
  ['calendar', '看了看日历'],
  ['heartbeat', '听了听心跳'],
  ['book', '翻了翻书架'],
  ['conflict', '看了看来历书'],
  ['windowsill', '在窗台停了停'],
  ['notebook', '翻了翻手边的本子'],
  ['room', '在房间里走了走'],
  ['supabase', '查了查家里的记录'],
  ['mcp', '用了一下外面的工具'],
]

export function toolWarmCopy(event: ToolEvent): string {
  const target = toolName(event).toLowerCase()
  const exact = EXACT_COPY[target]
  if (exact) return exact
  for (const [prefix, copy] of PREFIX_COPY) {
    if (target.startsWith(prefix)) return copy
  }
  // 最后的兜底也别落到 includes：错说一件事不如说得含糊。
  for (const [fragment, copy] of PREFIX_COPY) {
    if (target.includes(fragment)) return copy
  }
  return '认真处理了一下'
}

export function toolState(event: ToolEvent): string {
  if (event.phase === 'tool_start') return '进行中'
  if (event.ok === false) return '遇到一点阻塞'
  return '完成'
}
