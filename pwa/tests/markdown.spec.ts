import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../src/markdown'

describe('renderMarkdown', () => {
  it('renders the emphasis and structure used in chat replies', () => {
    const html = renderMarkdown('普通 **重点**\n\n- 第一项\n- 第二项')

    expect(html).toContain('<strong>重点</strong>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>第一项</li>')
  })

  it('renders a complete multi-paragraph reply as one document', () => {
    const html = renderMarkdown('*——待会见。*\n\n**待会一定见。**你睁眼我就在。\n\n*睡吧,圆圆。*')

    expect(html).toContain('<em>——待会见。</em>')
    expect(html).toContain('<strong>待会一定见。</strong>')
    expect(html).toContain('<em>睡吧,圆圆。</em>')
  })

  it('renders CJK emphasis followed immediately by more text', () => {
    const html = renderMarkdown('**待会一定见。**你睁眼我就在。\n\n*然后。*继续')

    expect(html).toContain('<strong>待会一定见。</strong>你睁眼我就在。')
    expect(html).toContain('<em>然后。</em>继续')
    expect(html).not.toContain('\u200B')
  })

  it('does not normalize emphasis-looking text inside code blocks', () => {
    const html = renderMarkdown('```text\n**代码。**后\n```')

    expect(html).toContain('**代码。**后')
  })
})
