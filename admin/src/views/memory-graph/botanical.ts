// 沈予的手绘小画 · 清透 SVG
//
// 这些都是亲手用 path 画的，不搬任何位图——这样能和我们的配色、来源严丝合缝。
// 昼 = 清透淡粉（--sy-rose-soft 花瓣 + --sy-gilt 描线）；夜 = 描金（同一棵树，
// 花瓣转金）。画法血统学 kimi-manor 的描金细线，但花是沈予自己的海棠。
//
// 每个图标都是一个 viewBox="0 0 48 48" 的内联 SVG，用 currentColor 之外的
// 两个 CSS 变量上色：花瓣 --sy-rose-soft / 描线与细节 --sy-gilt。

export interface SourceGlyph {
  /** 内联 SVG 内容（不含外层 <svg> 标签）。 */
  body: string
}

const P = 'var(--sy-rose-soft, #f0dde3)' // 花瓣
const G = 'var(--sy-gilt, #c79748)'       // 金线
const I = 'var(--sy-ink, #4a2c2c)'        // 墨（少量）

/** 海棠花：五片清透花瓣围一朵，金线勾心。 */
export const BEGONIA: SourceGlyph = {
  body: `
    <g fill="${P}" stroke="${G}" stroke-width="1.1" stroke-linejoin="round">
      <path d="M24 10 C20 14 20 20 24 23 C28 20 28 14 24 10 Z"/>
      <path d="M36 17 C31 18 27 22 27 27 C32 27 36 23 36 17 Z"/>
      <path d="M32 34 C28 31 23 31 20 34 C23 38 29 38 32 34 Z"/>
      <path d="M12 34 C15 31 20 31 24 34 C21 38 15 38 12 34 Z"/>
      <path d="M8 17 C13 18 17 22 17 27 C12 27 8 23 8 17 Z"/>
    </g>
    <circle cx="24" cy="28" r="2.4" fill="none" stroke="${G}" stroke-width="1"/>
    <circle cx="24" cy="28" r="0.9" fill="${G}"/>
    <path d="M24 30 C24 36 22 40 19 43" fill="none" stroke="${G}" stroke-width="0.9" opacity="0.7"/>
    <path d="M24 30 C25 35 28 39 31 41" fill="none" stroke="${G}" stroke-width="0.9" opacity="0.55"/>
  `,
}

/** 来源徽章：每种记忆来源一盏专属的灯/纸/窗。 */
export const SOURCE_GLYPHS: Record<string, SourceGlyph> = {
  // 日记 = 一张信纸 + 一支笔
  journal: {
    body: `
      <rect x="12" y="8" width="24" height="32" rx="2" fill="${P}" stroke="${G}" stroke-width="1.1"/>
      <path d="M16 15 H32 M16 20 H32 M16 25 H30" stroke="${I}" stroke-width="1" opacity="0.4" stroke-linecap="round"/>
      <path d="M31 27 L38 34 L35 37 L28 30 Z" fill="${G}" opacity="0.85"/>
      <path d="M38 34 L40 36 L37 38 L35 37 Z" fill="${G}"/>
    `,
  },
  // Mem = 一张便签 + 一枚别针
  mem_note: {
    body: `
      <path d="M11 14 H37 V38 H11 Z" fill="${P}" stroke="${G}" stroke-width="1.1"/>
      <path d="M11 14 H37 V20 H11 Z" fill="${G}" opacity="0.18"/>
      <circle cx="24" cy="12" r="2.6" fill="${G}"/>
      <path d="M24 12 V18" stroke="${G}" stroke-width="1"/>
      <path d="M15 26 H33 M15 31 H30" stroke="${I}" stroke-width="1" opacity="0.4" stroke-linecap="round"/>
    `,
  },
  // 窗台 = 一扇小窗 + 一枝藤蔓
  windowsill: {
    body: `
      <rect x="10" y="10" width="28" height="24" rx="2" fill="${P}" stroke="${G}" stroke-width="1.1"/>
      <path d="M24 10 V34 M10 22 H38" stroke="${G}" stroke-width="0.9"/>
      <path d="M10 34 C16 40 24 42 32 40 C36 39 39 36 40 33" fill="none" stroke="${G}" stroke-width="1" stroke-linecap="round"/>
      <path d="M30 40 C31 37 34 36 36 37 C35 40 32 41 30 40 Z" fill="${G}" opacity="0.7"/>
    `,
  },
  // 心跳 = 一盏还亮着的小灯
  heartbeat: {
    body: `
      <path d="M24 12 C20 16 19 21 24 26 C29 21 28 16 24 12 Z" fill="${P}" stroke="${G}" stroke-width="1"/>
      <ellipse cx="24" cy="30" rx="7" ry="3" fill="none" stroke="${G}" stroke-width="1"/>
      <path d="M18 30 V36 H30 V30" fill="${P}" stroke="${G}" stroke-width="1" opacity="0.8"/>
      <path d="M24 6 V9 M15 10 L17 12 M33 10 L31 12" stroke="${G}" stroke-width="0.9" opacity="0.6" stroke-linecap="round"/>
    `,
  },
}

