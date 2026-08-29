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

// \u8BED\u8A00\u672A\u6807\u6CE8\u65F6 highlightAuto \u4F1A\u9010\u4E2A\u8BED\u6CD5\u8BD5\uFF0C\u5B9E\u6D4B 3.28ms/\u5757\uFF0C\u800C\u6307\u5B9A\u8BED\u8A00\u53EA\u8981
// 0.10ms\uFF0833 \u500D\uFF09\u3002\u6D41\u5F0F\u6BCF chunk \u90FD\u6E32\u67D3\uFF0C\u8FD9\u4E2A\u5F00\u9500\u4E0D\u80FD\u8FDB\u5FAA\u73AF\uFF0C\u6240\u4EE5\uFF1A
//   - \u6D41\u5F0F\u671F\u95F4\u6574\u4F53\u8DF3\u8FC7\u9AD8\u4EAE\uFF08highlight: false\uFF09\uFF0C\u6536\u5C3E\u518D\u8865\u4E00\u6B21\uFF1B
//   - \u731C\u8BED\u8A00\u53EA\u5BF9\u77ED\u4EE3\u7801\u5757\u505A\uFF0C\u957F\u5757\u5B81\u53EF\u4E0D\u4E0A\u8272\u4E5F\u4E0D\u62D6\u4F4F\u4E3B\u7EBF\u7A0B\u3002
const AUTO_HIGHLIGHT_MAX_CHARS = 2000

// \u540C\u4E00\u6BB5\u6B63\u6587\u5728\u4E00\u6B21\u4F1A\u8BDD\u91CC\u4F1A\u88AB\u6E32\u67D3\u5F88\u591A\u6B21\uFF08\u7236\u7EA7\u91CD\u6E32\u67D3\u3001\u5207 variant\u3001\u5F00\u5408\u5F39\u5C42\uFF09\u3002
// \u7ED3\u679C\u53EA\u53D6\u51B3\u4E8E\u5165\u53C2\uFF0C\u7F13\u5B58\u5B89\u5168\u3002\u4E0A\u9650\u6309"\u4E00\u5C4F\u5386\u53F2 + \u6D41\u5F0F\u5C3E\u5DF4"\u53D6\uFF0C\u8D85\u4E86\u4E22\u6700\u65E7\u7684\u3002
const RENDER_CACHE_LIMIT = 120
const renderCache = new Map<string, string>()

function cacheKey(source: string, highlight: boolean): string {
  return `${highlight ? 'h' : 'p'}:${source}`
}

function highlightCodeBlocks(document: Document) {
  for (const code of document.querySelectorAll('pre code')) {
    const text = code.textContent || ''
    const language = Array.from(code.classList)
      .find((name) => name.startsWith('language-'))
      ?.slice('language-'.length)
    if (language && hljs.getLanguage(language)) {
      code.innerHTML = hljs.highlight(text, { language }).value
    } else if (text.length <= AUTO_HIGHLIGHT_MAX_CHARS) {
      code.innerHTML = hljs.highlightAuto(text).value
    } else {
      continue
    }
    code.classList.add('hljs')
  }
}

export function renderMarkdown(source: string, options: { highlight?: boolean } = {}): string {
  if (!source) return ''
  const highlight = options.highlight !== false
  const key = cacheKey(source, highlight)
  const cached = renderCache.get(key)
  if (cached !== undefined) return cached

  const parsed = String(marked.parse(normalizeCjkEmphasis(source)))
  const document = new DOMParser().parseFromString(parsed, 'text/html')
  if (highlight) highlightCodeBlocks(document)
  const html = DOMPurify.sanitize(document.body.innerHTML.replace(/ \u200B/g, '').replace(/\u200B/g, ''), {
    USE_PROFILES: { html: true },
  })

  if (renderCache.size >= RENDER_CACHE_LIMIT) {
    const oldest = renderCache.keys().next()
    if (!oldest.done) renderCache.delete(oldest.value)
  }
  renderCache.set(key, html)
  return html
}

// \u6D4B\u8BD5\u4E0E\u5185\u5B58\u8BCA\u65AD\u7528\uFF1B\u751F\u4EA7\u4EE3\u7801\u4E0D\u8BE5\u9700\u8981\u624B\u52A8\u6E05\u7F13\u5B58\u3002
export function clearMarkdownCache() {
  renderCache.clear()
}
