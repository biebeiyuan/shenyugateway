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

  it('supports valid nested emphasis delimiters', () => {
    const html = renderMarkdown('*就像这样**这种类型**发消息*')

    expect(html).toContain('<em>就像这样<strong>这种类型</strong>发消息</em>')
  })

  it('keeps an unmatched inner delimiter as text without breaking the reply', () => {
    const html = renderMarkdown('有的时候*就像这样**这种类型*发消息')

    expect(html).toContain('<em>就像这样**这种类型</em>发消息')
    expect(html).not.toContain('<em><em>')
  })

  it.each([
    ['*外层 **内层** 后续*', '<em>外层 <strong>内层</strong> 后续</em>'],
    ['**外层 *内层* 后续**', '<strong>外层 <em>内层</em> 后续</strong>'],
    ['***加粗斜体***', '<em><strong>加粗斜体</strong></em>'],
    ['__外层 _内层_ 后续__', '<strong>外层 <em>内层</em> 后续</strong>'],
    ['~~删除 **重点**~~', '<del>删除 <strong>重点</strong></del>'],
    ['*外层 **内层。**后续*', '<em>外层 <strong>内层。</strong>后续</em>'],
    ['**外层 *内层。*后续**', '<strong>外层 <em>内层。</em>后续</strong>'],
  ])('handles nested emphasis variant: %s', (source, expected) => {
    expect(renderMarkdown(source)).toContain(expected)
  })

  it('keeps emphasis markers inside links as inline Markdown', () => {
    const html = renderMarkdown('[**重点**](https://example.com)')

    expect(html).toContain('<a href="https://example.com"><strong>重点</strong></a>')
  })
})
