import type { CSSProperties } from 'react'

export type ExistingSubtitleStyle = 'minimal' | 'cinematic' | 'shorts'

export const DEFAULT_EXISTING_SUBTITLE_DURATION_SEC = 12

/** Mirrors backend `video_service._SUBTITLE_STYLE_PARAMS` for preview alignment. */
export const SUBTITLE_PREVIEW_PARAMS: Record<
  ExistingSubtitleStyle,
  {
    fontFrac: number
    marginFrac: number
    maxWidthFrac: number
    padX: number
    padY: number
    maxLines: number
    bold: boolean
    bgAlpha: number
  }
> = {
  minimal: {
    fontFrac: 0.028,
    marginFrac: 0.075,
    maxWidthFrac: 0.88,
    padX: 16,
    padY: 10,
    maxLines: 2,
    bold: false,
    bgAlpha: 145,
  },
  cinematic: {
    fontFrac: 0.034,
    marginFrac: 0.095,
    maxWidthFrac: 0.82,
    padX: 22,
    padY: 12,
    maxLines: 2,
    bold: false,
    bgAlpha: 158,
  },
  shorts: {
    fontFrac: 0.042,
    marginFrac: 0.115,
    maxWidthFrac: 0.9,
    padX: 16,
    padY: 11,
    maxLines: 3,
    bold: true,
    bgAlpha: 178,
  },
}

export type ExistingVideoLayout = {
  intrinsicW: number
  intrinsicH: number
  displayW: number
  displayH: number
}

export const EMPTY_VIDEO_LAYOUT: ExistingVideoLayout = {
  intrinsicW: 0,
  intrinsicH: 0,
  displayW: 0,
  displayH: 0,
}

export function isExistingSubtitleStyle(style: string): style is ExistingSubtitleStyle {
  return style === 'minimal' || style === 'cinematic' || style === 'shorts'
}

export function inferExistingVideoPortrait(
  intrinsicW: number,
  intrinsicH: number,
  subtitleStyle: string,
): boolean {
  if (intrinsicW > 0 && intrinsicH > 0) return intrinsicH > intrinsicW
  return subtitleStyle === 'shorts'
}

export function getRecommendedSubtitleMaxChars(
  subtitleStyle: string,
  portrait: boolean,
): number {
  if (subtitleStyle === 'shorts') return portrait ? 100 : 120
  if (subtitleStyle === 'cinematic') return portrait ? 120 : 150
  if (subtitleStyle === 'minimal') return portrait ? 110 : 140
  return 140
}

function adjustedParams(style: ExistingSubtitleStyle, portrait: boolean) {
  const base = SUBTITLE_PREVIEW_PARAMS[style]
  if (!portrait) return base
  return {
    ...base,
    maxWidthFrac: Math.min(0.92, base.maxWidthFrac + 0.04),
    marginFrac: Math.max(0.068, base.marginFrac - 0.022),
  }
}

let measureCanvas: HTMLCanvasElement | null = null

function measureCtx(): CanvasRenderingContext2D {
  if (!measureCanvas) measureCanvas = document.createElement('canvas')
  const ctx = measureCanvas.getContext('2d')
  if (!ctx) throw new Error('Canvas 2D unavailable')
  return ctx
}

function measureWidth(text: string, fontPx: number, bold: boolean): number {
  const ctx = measureCtx()
  ctx.font = `${bold ? '700' : '500'} ${fontPx}px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
  return ctx.measureText(text).width
}

function truncateWithEllipsis(
  text: string,
  maxWidth: number,
  fontPx: number,
  bold: boolean,
): string {
  if (!text.trim()) return ''
  if (measureWidth(text, fontPx, bold) <= maxWidth) return text
  const ell = '…'
  let lo = 0
  let hi = text.length
  let best = ell
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2)
    const trial = `${text.slice(0, mid).trimEnd()}${ell}`.trim()
    if (measureWidth(trial, fontPx, bold) <= maxWidth) {
      best = trial
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return best
}

export function wrapSubtitlePreviewLines(
  text: string,
  style: ExistingSubtitleStyle,
  layout: ExistingVideoLayout,
): { lines: string[]; truncated: boolean; fontPx: number; maxTextWidthPx: number } {
  const portrait = inferExistingVideoPortrait(layout.intrinsicW, layout.intrinsicH, style)
  const params = adjustedParams(style, portrait)
  const refH = layout.intrinsicH > 0 ? layout.intrinsicH : layout.displayH || 720
  const refW = layout.intrinsicW > 0 ? layout.intrinsicW : layout.displayW || 1280
  const scale = layout.displayH > 0 && refH > 0 ? layout.displayH / refH : 1
  const fontPx = Math.max(11, refH * params.fontFrac * scale)
  const maxTextWidthPx = refW * params.maxWidthFrac * scale

  const normalized = text.replace(/\n/g, ' ').trim()
  if (!normalized) {
    return { lines: [''], truncated: false, fontPx, maxTextWidthPx }
  }

  const words = normalized.split(/\s+/)
  const lines: string[] = []
  const remaining = [...words]
  const maxLines = params.maxLines

  while (remaining.length > 0 && lines.length < maxLines) {
    const lineWords: string[] = []
    while (remaining.length > 0) {
      const next = remaining[0]
      const trial = lineWords.length ? `${lineWords.join(' ')} ${next}` : next
      if (measureWidth(trial, fontPx, params.bold) <= maxTextWidthPx) {
        lineWords.push(remaining.shift()!)
      } else {
        break
      }
    }
    if (lineWords.length) {
      lines.push(lineWords.join(' '))
    } else if (remaining.length) {
      lines.push(truncateWithEllipsis(remaining.shift()!, maxTextWidthPx, fontPx, params.bold))
    }
  }

  let truncated = remaining.length > 0
  if (remaining.length > 0 && lines.length > 0) {
    const merged = `${lines[lines.length - 1]} ${remaining.join(' ')}`.trim()
    lines[lines.length - 1] = truncateWithEllipsis(merged, maxTextWidthPx, fontPx, params.bold)
    truncated = true
  } else if (remaining.length > 0 && lines.length === 0) {
    lines.push(truncateWithEllipsis(remaining.join(' '), maxTextWidthPx, fontPx, params.bold))
    truncated = true
  }

  return {
    lines: lines.slice(0, maxLines),
    truncated,
    fontPx,
    maxTextWidthPx,
  }
}

export function computeSubtitleOverlayStyle(
  style: ExistingSubtitleStyle,
  layout: ExistingVideoLayout,
  fontPx: number,
): CSSProperties {
  const portrait = inferExistingVideoPortrait(layout.intrinsicW, layout.intrinsicH, style)
  const params = adjustedParams(style, portrait)
  const refH = layout.intrinsicH > 0 ? layout.intrinsicH : layout.displayH || 720
  const scale = layout.displayH > 0 && refH > 0 ? layout.displayH / refH : 1
  const padX = params.padX * scale
  const padY = params.padY * scale
  const bottomPx = Math.max(8, layout.displayH * params.marginFrac)
  const bgAlpha = params.bgAlpha / 255

  return {
    bottom: `${bottomPx}px`,
    maxWidth: `${params.maxWidthFrac * 100}%`,
    fontSize: `${fontPx}px`,
    padding: `${padY}px ${padX}px`,
    lineHeight: 1.25,
    background: `rgba(12, 12, 18, ${bgAlpha.toFixed(3)})`,
  }
}
