import type { ExistingSubtitleStyle, ExistingVideoLayout } from './existingSubtitleUtils'
import { computeSubtitleOverlayStyle, wrapSubtitlePreviewLines } from './existingSubtitleUtils'

type Props = {
  text: string
  style: ExistingSubtitleStyle
  layout: ExistingVideoLayout
}

export function ExistingVideoSubtitleOverlay({ text, style, layout }: Props) {
  const fit = wrapSubtitlePreviewLines(text, style, layout)
  const boxStyle = computeSubtitleOverlayStyle(style, layout, fit.fontPx)

  return (
    <div
      className={`existing-subtitle-overlay existing-subtitle-overlay--${style}`}
      style={boxStyle}
      aria-hidden
    >
      {fit.lines.join('\n')}
    </div>
  )
}
