export const ECHO_OPEN_MARKER = '[回响]'
export const ECHO_CLOSE_MARKER = '[/回响]'

export type EchoSplit = {
  content: string
  echo: string
  matched: boolean
}

export function splitEcho(value: string): EchoSplit {
  const source = String(value || '')
  const leading = source.length - source.trimStart().length
  if (!source.slice(leading).startsWith(ECHO_OPEN_MARKER)) {
    return { content: source, echo: '', matched: false }
  }
  const echoStart = leading + ECHO_OPEN_MARKER.length
  const closeIndex = source.indexOf(ECHO_CLOSE_MARKER, echoStart)
  if (closeIndex < 0) {
    return { content: '', echo: source.slice(echoStart), matched: true }
  }
  return {
    content: source.slice(closeIndex + ECHO_CLOSE_MARKER.length),
    echo: source.slice(echoStart, closeIndex),
    matched: true,
  }
}

export function joinEcho(content: string, echo: string): string {
  const echoText = String(echo || '')
  return echoText.trim()
    ? `${ECHO_OPEN_MARKER}${echoText}${ECHO_CLOSE_MARKER}${String(content || '')}`
    : String(content || '')
}
