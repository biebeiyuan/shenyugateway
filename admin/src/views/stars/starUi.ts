import type { StarCandidate, StarGraphLink, StarItem } from '@/api/stars'

export type MapConstellation = {
  key: string
  name: string
  links: StarGraphLink[]
  starIds: string[]
  stars: StarItem[]
}

export function formatTime(value?: string | null): string {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}

export function rootLabel(star: Pick<StarItem, 'chord' | 'chord_root'>): string {
  return star.chord || star.chord_root || '无和弦'
}

export function normalizeRoot(root?: string | null): string {
  const value = (root || '').trim().toUpperCase()
  const flatMap: Record<string, string> = {
    DB: 'C#',
    EB: 'D#',
    GB: 'F#',
    AB: 'G#',
    BB: 'A#',
  }
  return flatMap[value] || value
}

export function rootFromStar(star: Pick<StarItem, 'chord' | 'chord_root'>): string {
  return normalizeRoot(star.chord_root || star.chord.match(/[A-G](?:#|b)?/i)?.[0])
}

export function sourceMeta(star: StarItem | StarCandidate): string {
  return [
    star.session_tag ? `session ${star.session_tag}` : '',
    star.source_model || '',
    star.source_session_id ? `source ${String(star.source_session_id).slice(0, 8)}` : '',
    star.created_at ? `created ${formatTime(star.created_at)}` : '',
  ].filter(Boolean).join(' · ')
}

export function feedbackLabel(value: string): string {
  if (value === 'positive') return '这颗会更亮'
  if (value === 'negative') return '已记为不该反'
  if (value === 'skipped') return '先轻轻放过'
  if (value === 'connected') return '已连成星座'
  if (value === 'should_surface') return '记为该推上来'
  return '已记录'
}

export function scoreParts(candidate: StarCandidate): string {
  const scores = candidate.scores || {}
  const labels: Array<[string, string]> = [
    ['content_score', '内容'],
    ['harmony_score', '和声'],
    ['chord_score', '和弦'],
    ['keyword_score', '词'],
    ['actr_score', '亮度'],
  ]
  return labels
    .filter(([key]) => scores[key] !== undefined)
    .map(([key, label]) => `${label} ${scores[key]}`)
    .join(' · ')
}

export function sortLinks(links: StarGraphLink[]): StarGraphLink[] {
  return [...links].sort((left, right) => {
    const leftPosition = typeof left.position === 'number' ? left.position : Number.MAX_SAFE_INTEGER
    const rightPosition = typeof right.position === 'number' ? right.position : Number.MAX_SAFE_INTEGER
    if (leftPosition !== rightPosition) return leftPosition - rightPosition
    return String(left.last_confirmed_at || '').localeCompare(String(right.last_confirmed_at || ''))
      || `${left.source}:${left.target}`.localeCompare(`${right.source}:${right.target}`)
  })
}

export function orderedStarIdsFromLinks(links: StarGraphLink[]): string[] {
  const result: string[] = []
  for (const link of sortLinks(links)) {
    if (!result.includes(link.source)) result.push(link.source)
    if (!result.includes(link.target)) result.push(link.target)
  }
  return result
}

export function constellationsFromGraph(stars: StarItem[], links: StarGraphLink[]): MapConstellation[] {
  const starById = new Map(stars.map((star) => [star.id, star]))
  const groups = new Map<string, StarGraphLink[]>()
  for (const link of links) {
    const key = link.name || link.id || [link.source, link.target].sort().join(':')
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)?.push(link)
  }
  return Array.from(groups.entries())
    .map(([key, groupLinks]) => {
      const sortedLinks = sortLinks(groupLinks)
      const starIds = orderedStarIdsFromLinks(sortedLinks)
      return {
        key,
        name: sortedLinks[0]?.name || '未命名星座',
        links: sortedLinks,
        starIds,
        stars: starIds.map((id) => starById.get(id)).filter((star): star is StarItem => Boolean(star)),
      }
    })
    .filter((item) => item.stars.length >= 2)
    .sort((left, right) => left.name.localeCompare(right.name) || left.key.localeCompare(right.key))
}
