import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import { marked } from 'marked'

marked.setOptions({
  gfm: true,
  breaks: true,
})

const ZERO_WIDTH_SENTINEL = '\u200B'
const CJK_EMPHASIS_EDGE = /(\*\*|(?<!\*)\*)([^*\n]+?)((?![*_`])[\p{P}\p{S}])\1(?=\S)/gu
const MARKDOWN_CODE_SEGMENT = /(`{3,}[\s\S]*?`{3,}|~{3,}[\s\S]*?~{3,}|`[^`\n]*`)/g

// Marked follows CommonMark's flanking rules, which reject CJK punctuation
// directly beside an emphasis delimiter. Add invisible boundaries around those
// delimiters, then remove them from the parsed DOM so the displayed text stays exact.
function normalizeCjkEmphasis(source: string): string {
  return source
    .split(MARKDOWN_CODE_SEGMENT)
    .map((segment, index) => index % 2 === 1
      ? segment
      : segment.replace(CJK_EMPHASIS_EDGE, `$1$2$3${ZERO_WIDTH_SENTINEL}$1 ${ZERO_WIDTH_SENTINEL}`))
    .join('')
}

export function renderMarkdown(source: string): string {
  if (!source) return ''
  const parsed = String(marked.parse(normalizeCjkEmphasis(source)))
  const document = new DOMParser().parseFromString(parsed, 'text/html')
  for (const code of document.querySelectorAll('pre code')) {
    const text = code.textContent || ''
    const language = Array.from(code.classList)
      .find((name) => name.startsWith('language-'))
      ?.slice('language-'.length)
    const result = language && hljs.getLanguage(language)
      ? hljs.highlight(text, { language }).value
      : hljs.highlightAuto(text).value
    code.innerHTML = result
    code.classList.add('hljs')
  }
  return DOMPurify.sanitize(document.body.innerHTML.replace(/ \u200B/g, '').replace(/\u200B/g, ''), {
    USE_PROFILES: { html: true },
  })
}
