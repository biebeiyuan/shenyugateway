import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../src/markdown'

describe('renderMarkdown', () => {
  it('renders the emphasis and structure used in chat replies', () => {
    const html = renderMarkdown('普通 **重点**\n\n- 第一项\n- 第二项')

    expect(html).toContain('<strong>重点</strong>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>第一项</li>')
  })
})
