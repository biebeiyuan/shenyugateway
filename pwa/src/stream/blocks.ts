import { marked } from 'marked'
import { textLength } from '../utils'

// Markdown 块边界。
//
// 过程条要插回正文中间（"写一段 → 调工具 → 再写一段"），就得把正文切开。按字符
// 偏移直接切会切进块内部：`\n\n` 出现在代码块里是合法的，切完变成两个代码块、
// 第二半还丢了语言标注；松散列表 `- 一\n\n- 二` 同样被切成两个列表。2026-07-29
// 那次就是因此把交错渲染整个删掉、改成过程条全部堆在正文之前的。
//
// 所以边界必须由解析器给，而不是正则猜。`marked.lexer` 的 token 顺序拼回来无损
// 等于原文，于是每个 token 的结束位置就是一个安全切点。
//
// 单位要小心：`textOffset` 数的是码点（utils.textLength，为了 emoji 不错位），
// 而 `raw.length` 数的是 UTF-16 单元。一个 emoji 就能让两者差 1，所以这里统一
// 换算成码点再对外。

export type BlockSpan = {
  // 码点单位，[start, end)
  start: number
  end: number
  text: string
}

/**
 * 把正文切成 Markdown 块。`space` token（纯空行）并入前一块的尾部，这样拼接
 * 回来仍然等于原文，块之间也不会多出空段落。
 */
export function markdownBlocks(content: string): BlockSpan[] {
  if (!content) return []
  let tokens: { raw: string }[]
  try {
    tokens = marked.lexer(content) as { raw: string }[]
  } catch {
    // 解析失败（流式中途的半截语法）就当成一整块，不要因此丢正文。
    return [{ start: 0, end: textLength(content), text: content }]
  }

  const spans: BlockSpan[] = []
  let utf16 = 0
  let codepoint = 0
  for (const token of tokens) {
    const raw = String(token.raw || '')
    if (!raw) continue
    utf16 += raw.length
    const nextCodepoint = textLength(content.slice(0, utf16))
    const isBlank = !raw.trim()
    if (isBlank && spans.length) {
      // 纯空行归入上一块，保持"拼回来等于原文"。
      const last = spans[spans.length - 1]
      last.end = nextCodepoint
      last.text += raw
    } else {
      spans.push({ start: codepoint, end: nextCodepoint, text: raw })
    }
    codepoint = nextCodepoint
  }
  return spans
}

/**
 * 把一个过程偏移吸附到块边界。
 *
 * 落在块内部时吸附到该块**之后**——工具确实发生在这段文字写完前后，落在后面
 * 读起来才是自然顺序（圆圆 2026-08-30 确认）。
 */
export function snapToBlockBoundary(blocks: BlockSpan[], offset: number): number {
  if (!blocks.length) return 0
  for (const block of blocks) {
    if (offset <= block.start) return block.start
    if (offset < block.end) return block.end
  }
  return blocks[blocks.length - 1].end
}
