export type PwaBuildInfo = {
  schema: 1
  buildId: string
  revision: string
  builtAt: string
}

const UNBUILT_INFO: PwaBuildInfo = {
  schema: 1,
  buildId: 'source-unbuilt',
  revision: 'unknown',
  builtAt: 'unknown',
}

export function parsePwaBuildInfo(value: unknown): PwaBuildInfo | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const candidate = value as Record<string, unknown>
  if (candidate.schema !== 1) return null
  if (typeof candidate.buildId !== 'string' || !candidate.buildId.trim()) return null
  if (typeof candidate.revision !== 'string' || !candidate.revision.trim()) return null
  if (typeof candidate.builtAt !== 'string' || !candidate.builtAt.trim()) return null

  return {
    schema: 1,
    buildId: candidate.buildId,
    revision: candidate.revision,
    builtAt: candidate.builtAt,
  }
}

export const activePwaBuildInfo = parsePwaBuildInfo(
  typeof __PWA_BUILD_INFO__ === 'undefined' ? null : __PWA_BUILD_INFO__,
) || UNBUILT_INFO

export function samePwaBuild(active: PwaBuildInfo, deployed: PwaBuildInfo): boolean {
  return active.buildId === deployed.buildId
}
