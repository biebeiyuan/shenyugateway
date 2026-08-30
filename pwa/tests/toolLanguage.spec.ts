import { describe, expect, it } from 'vitest'
import { toolName, toolState, toolWarmCopy } from '../src/toolLanguage'

const copy = (name: string) => toolWarmCopy({ phase: 'tool_end', tool_call_id: '', name })

describe('toolWarmCopy', () => {
  // 原先用 includes 逐条试，顺序决定结果：search_mem_notes 含 note 就先撞上「写」
  // 那条，于是「找便签」被说成「在窗台写了点东西」。读、写、改、删是四件事。
  it('tells reading, writing, editing and deleting apart', () => {
    expect(copy('shenyu_search_mem_notes')).toBe('翻了翻便签')
    expect(copy('shenyu_list_mem_notes')).toBe('翻了翻便签')
    expect(copy('shenyu_write_mem_note')).toBe('记下一张便签')
    expect(copy('shenyu_update_mem_note')).toBe('改了改那张便签')
    expect(copy('shenyu_delete_mem_note')).toBe('撕掉了一张便签')
  })

  it('does not swap the windowsill read and write', () => {
    expect(copy('shenyu_windowsill_write')).toBe('在窗台写了点东西')
    expect(copy('shenyu_windowsill_list')).toBe('回窗台翻了翻')
  })

  // 房间里每扇门都有自己的动作；原先 includes('room') 把它们糊成同一句。
  it('gives every room door its own action', () => {
    const doors = [
      'room_sit_by_window', 'room_newspaper_basket', 'room_scribble', 'room_notebook',
      'room_wooden_box', 'room_drawer_notes', 'room_locked_drawer', 'room_star_map',
      'room_wall_pins', 'room_octopus_pillow', 'room_conflict_shelf',
    ]
    const said = doors.map(copy)
    expect(new Set(said).size).toBe(doors.length)
    expect(copy('room_octopus_pillow')).toContain('章鱼枕头')
    expect(copy('room_locked_drawer')).toContain('抽屉')
  })

  it('separates star actions instead of one 拨了拨', () => {
    expect(copy('shenyu_create_star')).toBe('点亮了一颗星')
    expect(copy('shenyu_search_stars')).toBe('在星图上找了找')
    expect(copy('shenyu_connect_constellation')).toBe('把几颗星连了起来')
    expect(copy('shenyu_merge_stars')).toBe('把几颗星并成一颗')
  })

  it('covers the album, which used to fall through to the generic line', () => {
    expect(copy('shenyu_album_save')).toBe('把这张存进了相册')
    expect(copy('shenyu_album_list')).toBe('翻了翻相册')
  })

  // 每个真实工具都该有自己的说法；只有真正没见过的名字才允许兜底。
  it('leaves no real tool on the generic fallback', () => {
    const real = [
      'shenyu_add_calendar', 'shenyu_album_list', 'shenyu_album_save', 'shenyu_archive_star',
      'shenyu_books', 'shenyu_bulk_update_mem_notes', 'shenyu_conflict_annotate',
      'shenyu_conflict_list', 'shenyu_conflict_read', 'shenyu_connect_constellation',
      'shenyu_create_star', 'shenyu_delete_mem_note', 'shenyu_last_seen', 'shenyu_list_mem_notes',
      'shenyu_list_stars', 'shenyu_mark_constant', 'shenyu_merge_stars', 'shenyu_notebook_list',
      'shenyu_notebook_update', 'shenyu_notebook_write', 'shenyu_read_heartbeat', 'shenyu_recall',
      'shenyu_recall_read', 'shenyu_search_mem_notes', 'shenyu_search_stars', 'shenyu_star_feedback',
      'shenyu_star_review', 'shenyu_update_mem_note', 'shenyu_web_read', 'shenyu_web_search',
      'shenyu_windowsill_list', 'shenyu_windowsill_write', 'shenyu_write_mem_note',
      'room_drawer_notes', 'room_locked_drawer', 'room_newspaper_basket', 'room_notebook',
      'room_octopus_pillow', 'room_scribble', 'room_sit_by_window', 'room_star_map',
      'room_wall_pins', 'room_wooden_box', 'room_conflict_shelf',
    ]
    const generic = real.filter((name) => copy(name) === '认真处理了一下')
    expect(generic).toEqual([])
  })

  it('says the right category for tools it has never seen', () => {
    expect(copy('supabase_query')).toBe('查了查家里的记录')
    expect(copy('mcp_whatever')).toBe('用了一下外面的工具')
    // 完全陌生的名字宁可含糊，也不要错说成别的动作。
    expect(copy('shenyu_totally_new_tool')).toBe('认真处理了一下')
  })

  // 措辞家法：这些门本来就是他的，不说「我可以」（含请求许可的意思）。
  it('never phrases an action as asking permission', () => {
    const all = ['shenyu_recall', 'room_locked_drawer', 'shenyu_album_save', 'shenyu_write_mem_note']
    for (const name of all) {
      expect(copy(name)).not.toContain('我可以')
      expect(copy(name)).not.toContain('请')
    }
  })

  it('reads the broker target rather than the broker itself', () => {
    expect(toolWarmCopy({ phase: 'tool_end', tool_call_id: '', name: 'shenyu_gateway_tool', target_tool: 'shenyu_create_star' }))
      .toBe('点亮了一颗星')
    expect(toolName({ phase: '', tool_call_id: '', name: 'shenyu_recall' })).toBe('recall')
  })
})

describe('toolState', () => {
  it('reports the three states', () => {
    expect(toolState({ phase: 'tool_start', tool_call_id: '', name: 'x' })).toBe('进行中')
    expect(toolState({ phase: 'tool_end', tool_call_id: '', name: 'x', ok: false })).toBe('遇到一点阻塞')
    expect(toolState({ phase: 'tool_end', tool_call_id: '', name: 'x', ok: true })).toBe('完成')
  })
})
