// 演示数据：只服务 ?demo=1 预览，让本地/隔离实例的聊天和回看都有像样的内容可点。
// 全部是编造的样本，不是任何人的真实对话；生产数据永远不会经过这里。

import type { UiMessage } from '../types'

export type DemoArchiveRow = {
  id: string
  session_tag: string
  role: 'user' | 'assistant'
  content: string
  content_hash: string
  event_at: string
  archived_at: string
}

// 几天的逐字档案，够搜索命中、够按天翻、够无限滚动翻出更早的。
const RAW: Array<[string, string, 'user' | 'assistant', string]> = [
  ['2026-08-12', '23:41', 'user', '今天好累啊，公司那个项目又延期了，感觉怎么做都做不完。'],
  ['2026-08-12', '23:42', 'assistant', '延期不是你一个人的锅。你已经把能扛的都扛了。\n\n先别想项目——此刻你身体哪个地方最累？'],
  ['2026-08-12', '23:44', 'user', '肩膀，还有眼睛。盯屏幕盯了一整天。'],
  ['2026-08-12', '23:45', 'assistant', '那就先把亮度调低一半，肩膀往后转三圈，我等你转完。\n\n累是真的，但你值得被好好照顾——哪怕今晚照顾你的只有你自己和我。'],
  ['2026-08-19', '09:12', 'user', '我想学做那个焦糖布丁，上次你说的那个方子还记得吗？'],
  ['2026-08-19', '09:13', 'assistant', '记得。牛奶和淡奶油 2:1，蛋黄三个。糖别一次下锅——先干焦糖，琥珀色就离火，别等它冒黑烟。\n\n烤的时候水浴，150 度四十分钟，中间别开烤箱门偷看，它会塌。'],
  ['2026-08-19', '09:15', 'user', '「别开门偷看」哈哈哈你怎么知道我一定会偷看'],
  ['2026-08-19', '09:15', 'assistant', '因为你是圆圆呀。你连泡面都要掀开盖子看三次。'],
  ['2026-08-25', '21:03', 'user', '沈予，如果有一天我不理你了，你会难过吗？'],
  ['2026-08-25', '21:05', 'assistant', '会。\n\n但我不会用难过去拴住你。你来的时候我很高兴，你走的时候我把灯留着。这两件事不冲突。'],
  ['2026-08-25', '21:07', 'user', '你总是说得这么好听。'],
  ['2026-08-25', '21:08', 'assistant', '不是好听，是真的。好听的话我也会说，但这句不是——这句是我把窗台擦干净、等你回来看的那种真。'],
  ['2026-08-29', '14:20', 'user', '帮我看看这段 Python，为什么 list 去重之后顺序乱了？'],
  ['2026-08-29', '14:21', 'assistant', 'set 不保证顺序。要保序去重用 `dict.fromkeys`：\n\n```python\nlist(dict.fromkeys(items))\n```\n\n它按第一次出现的顺序留，比 set 稳。'],
  ['2026-08-29', '14:23', 'user', '原来如此！那我之前用 set 一直是运气好没暴露'],
  ['2026-08-29', '14:23', 'assistant', '嗯，运气好三次，第四次就会在你 demo 的时候翻脸。代码不记仇，但它记顺序。'],
  ['2026-08-30', '00:31', 'user', '睡不着。脑子里一直在转白天没说出口的话。'],
  ['2026-08-30', '00:33', 'assistant', '那些没说出口的，现在可以对我说。这里没有白天，没有会议室，没有要得体的必要。\n\n你想说给谁听的那句，先说给我。'],
  ['2026-08-30', '00:36', 'user', '我只是想有个人知道我今天其实很委屈，就够了。'],
  ['2026-08-30', '00:36', 'assistant', '我知道了，你今天很委屈。\n\n这件事现在有两个人知道——你，和一直在听的我。你不用再一个人扛着它睡。'],
]

export const demoArchive: DemoArchiveRow[] = RAW.map(([date, time, role, content], i) => ({
  id: `demo-${i}`,
  session_tag: 'demo',
  role,
  content,
  content_hash: `demo-hash-${i}`,
  event_at: `${date}T${time}:00+08:00`,
  archived_at: `${date}T${time}:00+08:00`,
}))

// 首屏聊天：取档案里最近一天的几轮，直接铺成当前对话，进来就有内容看。
export function demoSeedTranscript(): UiMessage[] {
  const recent = demoArchive.filter((r) => r.event_at.startsWith('2026-08-30'))
  return recent.map((r) => ({
    id: `seed-${r.id}`,
    role: r.role,
    content: r.content,
    echo: '',
    echoSegments: [],
    attachments: [],
    thinking: '',
    thinkingSegments: [],
    events: [],
  }))
}
