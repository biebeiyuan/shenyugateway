import { describe, expect, it } from 'vitest'
import { markdownBlocks, snapToBlockBoundary } from '../src/stream/blocks'
import { renderMarkdown } from '../src/markdown'
import { textLength } from '../src/utils'

describe('markdownBlocks', () => {
  it('splits on real block boundaries and rejoins losslessly', () => {
    const src = '第一段。\n\n```python\ndef a():\n\n    pass\n```\n\n- 一\n\n- 二\n\n最后。'
    const blocks = markdownBlocks(src)

    expect(blocks.map((b) => b.text).join('')).toBe(src)
    expect(blocks[blocks.length - 1].end).toBe(textLength(src))
    // 每块单独渲染都自洽：代码块和列表没有被切开。
    for (const block of blocks) {
      const html = renderMarkdown(block.text)
      expect((html.match(/<pre/g) || []).length).toBe((html.match(/<\/pre>/g) || []).length)
    }
  })

  // 这两个是 7 月删掉交错渲染的直接原因：空行出现在块内部是合法的。
  it('keeps a blank line inside a code fence in one block', () => {
    const blocks = markdownBlocks('```python\ndef a():\n\n    pass\n```')
    expect(blocks).toHaveLength(1)
    expect(renderMarkdown(blocks[0].text)).toContain('language-python')
  })

  it('keeps a loose list in one block', () => {
    const blocks = markdownBlocks('- 一\n\n- 二')
    expect(blocks).toHaveLength(1)
  })

  it('counts offsets in code points so emoji do not shift boundaries', () => {
    const src = '看🌊这个。\n\n第二段。'
    const blocks = markdownBlocks(src)
    expect(blocks[blocks.length - 1].end).toBe(textLength(src))
    expect(blocks.map((b) => b.text).join('')).toBe(src)
  })

  it('treats an unterminated fence as one block instead of losing text', () => {
    const src = '```python\nimport json'
    const blocks = markdownBlocks(src)
    expect(blocks.map((b) => b.text).join('')).toBe(src)
  })

  it('handles empty content', () => {
    expect(markdownBlocks('')).toEqual([])
  })
})

describe('snapToBlockBoundary', () => {
  const src = '第一段。\n\n```python\ndef a():\n\n    pass\n```\n\n最后。'
  const blocks = markdownBlocks(src)

  it('snaps an offset inside a block to after that block', () => {
    const insideCode = textLength(src.slice(0, src.indexOf('def a') + 2))
    const snapped = snapToBlockBoundary(blocks, insideCode)
    const codeBlock = blocks.find((b) => b.text.includes('```python'))!
    expect(snapped).toBe(codeBlock.end)
  })

  it('keeps an offset that already sits on a boundary', () => {
    expect(snapToBlockBoundary(blocks, blocks[0].end)).toBe(blocks[0].end)
    expect(snapToBlockBoundary(blocks, 0)).toBe(0)
  })

  it('clamps beyond the end and tolerates no blocks', () => {
    expect(snapToBlockBoundary(blocks, 99999)).toBe(blocks[blocks.length - 1].end)
    expect(snapToBlockBoundary([], 5)).toBe(0)
  })
})
