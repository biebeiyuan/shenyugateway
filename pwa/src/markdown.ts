import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import { marked } from 'marked'

marked.setOptions({
  gfm: true,
  breaks: true,
})

export function renderMarkdown(source: string): string {
  if (!source) return ''
  const parsed = String(marked.parse(source))
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
  return DOMPurify.sanitize(document.body.innerHTML, {
    USE_PROFILES: { html: true },
  })
}
