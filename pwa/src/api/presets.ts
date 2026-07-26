import type { UpstreamPreset } from '../types'

// Upstream presets are written by the Admin Config page into same-origin
// localStorage; the PWA only reads them. Keep this key in sync with
// admin/src/views/ConfigView.vue.
export const PRESETS_KEY = 'shenyu_upstream_presets'

export function readUpstreamPresets(): UpstreamPreset[] {
  try {
    const raw = JSON.parse(localStorage.getItem(PRESETS_KEY) || '{}')
    return Object.entries(raw).map(([name, value]) => {
      const preset = value as Partial<UpstreamPreset>
      return {
        name,
        url: preset.url || '',
        key: preset.key || '',
        protocol: preset.protocol || preset.proto || 'auto',
        extra_body: preset.extra_body || '',
        passthrough_headers: preset.passthrough_headers || [],
      }
    })
  } catch {
    return []
  }
}
