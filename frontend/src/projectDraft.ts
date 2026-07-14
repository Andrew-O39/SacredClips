export const PROJECT_DRAFT_KEY = 'sacredclips-project-draft'
export const DRAFT_VERSION = 1

export type DraftCreationMode = 'ai' | 'manual' | 'existing'
export type DraftVideoType = 'normal' | 'shorts'
export type DraftAspectRatio = '16:9' | '9:16' | '1:1'
export type DraftImageFitMode = 'fit' | 'fill'
export type DraftManualImageMode = 'upload' | 'generate' | 'placeholder'
export type DraftManualNarrationSource = 'tts' | 'upload'
export type DraftBackgroundMusic = 'none' | 'peaceful_piano' | 'ambient_pad' | 'soft_strings' | 'gentle_choir'
export type DraftMotionEffect = 'none' | 'gentle_zoom' | 'slow_pan' | 'ken_burns'
export type DraftMotionIntensity = 'subtle' | 'medium' | 'strong'
export type DraftSubtitleStyle = 'off' | 'minimal' | 'cinematic' | 'shorts'
export type DraftBrandingPosition = 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right'
export type DraftBrandingSize = 'small' | 'medium' | 'large'

export type DraftScene = {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
  image_url?: string | null
  image_mode?: DraftManualImageMode | null
  image_path?: string | null
}

export type DraftExistingSubtitle = {
  id: string
  start_seconds: number
  end_seconds: number
  text: string
}

export type DraftVideoResult = {
  video_path: string
  video_url: string
  script_text: string
  scenes: DraftScene[]
  used_ai: boolean
  narration_source?: DraftManualNarrationSource | null
  narration_audio_path?: string | null
}

export type ProjectDraft = {
  version: number
  savedAt: string
  creationMode: DraftCreationMode
  topic: string
  style: string
  videoType: DraftVideoType
  duration: number
  aspectRatio: DraftAspectRatio
  imageFitMode: DraftImageFitMode
  visualStyle: string
  editedScript: string
  editedScenes: DraftScene[]
  manualImageModes: Record<number, DraftManualImageMode>
  manualNarrationSource: DraftManualNarrationSource
  persistedManualNarration: { source: 'upload'; path: string } | null
  existingSubtitles: DraftExistingSubtitle[]
  existingSourceVideoPath: string
  existingSourceVideoUrl: string
  backgroundMusic: DraftBackgroundMusic
  backgroundMusicVolume: number
  motionEffect: DraftMotionEffect
  motionIntensity: DraftMotionIntensity
  subtitleStyle: DraftSubtitleStyle
  brandingEnabled: boolean
  brandingLogoPath: string
  brandingLogoUrl: string
  brandingPosition: DraftBrandingPosition
  brandingSize: DraftBrandingSize
  brandingOpacity: number
  activeRenderJobId: string | null
  latestResult: DraftVideoResult | null
  editMode: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function loadProjectDraft(): ProjectDraft | null {
  try {
    const raw = localStorage.getItem(PROJECT_DRAFT_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed)) return null
    if (parsed.version !== DRAFT_VERSION) return null
    if (typeof parsed.topic !== 'string') return null
    if (!['ai', 'manual', 'existing'].includes(String(parsed.creationMode))) return null
    if (!Array.isArray(parsed.editedScenes)) return null
    if (!Array.isArray(parsed.existingSubtitles)) return null
    return parsed as ProjectDraft
  } catch {
    return null
  }
}

export function saveProjectDraft(draft: ProjectDraft): boolean {
  try {
    localStorage.setItem(PROJECT_DRAFT_KEY, JSON.stringify(draft))
    return true
  } catch {
    return false
  }
}

export function clearProjectDraft(): void {
  try {
    localStorage.removeItem(PROJECT_DRAFT_KEY)
  } catch {
    /* ignore */
  }
}
