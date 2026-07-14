import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { ExistingVideoSubtitleOverlay } from './ExistingVideoSubtitleOverlay'
import {
  DEFAULT_EXISTING_SUBTITLE_DURATION_SEC,
  EMPTY_VIDEO_LAYOUT,
  type ExistingVideoLayout,
  getRecommendedSubtitleMaxChars,
  inferExistingVideoPortrait,
  isExistingSubtitleStyle,
  wrapSubtitlePreviewLines,
} from './existingSubtitleUtils'
import {
  clearProjectDraft,
  createDefaultExistingSubtitles,
  DEFAULT_PROJECT_STYLE,
  DEFAULT_PROJECT_TOPIC,
  DEFAULT_PROJECT_VISUAL_STYLE,
  DRAFT_VERSION,
  loadProjectDraft,
  saveProjectDraft,
  type ProjectDraft,
} from './projectDraft'
import { fetchRenderJob, formatJobStage, pollRenderJob, type RenderJobStatus } from './renderJobs'

const API_BASE_URL = 'http://localhost:8000'

/** Must match backend `image_service.STYLE_PROMPT_BLOCKS` labels. */
const VISUAL_STYLE_OPTIONS = [
  'Classical sacred art',
  'Cinematic realism',
  'Historical documentary',
  'Warm candlelit painting',
  'Minimal reverent illustration',
] as const

type VisualStyle = typeof VISUAL_STYLE_OPTIONS[number]
type AspectRatio = '16:9' | '9:16' | '1:1'
type VideoType = 'normal' | 'shorts'

type Scene = {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
  image_url?: string | null
  image_mode?: ManualImageMode | null
  image_path?: string | null
}

type CreationMode = 'ai' | 'manual' | 'existing'
type ManualImageMode = 'upload' | 'generate' | 'placeholder'
type ManualNarrationSource = 'tts' | 'upload'
type GenerationProfile = 'ai' | 'manual_tts' | 'manual_upload' | 'regenerate' | 'subtitles'
type ImageFitMode = 'fit' | 'fill'

type BackgroundMusic = 'none' | 'peaceful_piano' | 'ambient_pad' | 'soft_strings' | 'gentle_choir'

type MotionEffect = 'none' | 'gentle_zoom' | 'slow_pan' | 'ken_burns'

type MotionIntensity = 'subtle' | 'medium' | 'strong'

type SubtitleStyle = 'off' | 'minimal' | 'cinematic' | 'shorts'

type BrandingPosition = 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right'
type BrandingSize = 'small' | 'medium' | 'large'

type BrandingUploadResponse = {
  branding_logo_path: string
  branding_logo_url: string
}

function roundToHalfSecond(value: number): number {
  return Math.max(0.5, Math.round(value * 2) / 2)
}

function scenesForApiPayload(scenes: Scene[]): {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
  image_mode?: ManualImageMode
  image_path?: string
}[] {
  return scenes.map(s => ({
    index: s.index,
    text: s.text,
    keywords: s.keywords,
    duration_seconds: s.duration_seconds,
    ...(s.image_mode != null && s.image_mode !== undefined ? { image_mode: s.image_mode } : {}),
    ...(s.image_path ? { image_path: s.image_path } : {}),
  }))
}

function sanitizeScenesForPayload(scenes: Scene[]): {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
  image_mode?: ManualImageMode
  image_path?: string
}[] {
  return scenes.map(s => {
    const safeText = s.text.trim() || `Manual visual scene ${s.index}`
    const safeKeywords = (s.keywords || []).map(k => k.trim()).filter(Boolean)
    const safeDuration = Number.isFinite(s.duration_seconds) && s.duration_seconds > 0
      ? roundToHalfSecond(s.duration_seconds)
      : 10
    return {
      index: s.index,
      text: safeText,
      keywords: safeKeywords.length ? safeKeywords : ['manual scene'],
      duration_seconds: safeDuration,
      ...(s.image_mode != null && s.image_mode !== undefined ? { image_mode: s.image_mode } : {}),
      ...(s.image_path ? { image_path: s.image_path } : {}),
    }
  })
}

function splitScriptIntoScenes(script: string, targetTotalSeconds: number): Scene[] {
  const trimmed = script.trim()
  if (!trimmed) return []
  const blocks = trimmed.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean)
  const paragraphs = blocks.length ? blocks : [trimmed.replace(/\s+/g, ' ').trim()]
  const n = paragraphs.length
  const per = roundToHalfSecond(Math.max(8, targetTotalSeconds / n))
  return paragraphs.map((p, i) => ({
    index: i + 1,
    text: p.replace(/\n+/g, ' ').trim(),
    keywords: ['manual scene', `part ${i + 1}`],
    duration_seconds: per,
  }))
}

function reindexScenes(scenes: Scene[]): Scene[] {
  return scenes.map((scene, i) => ({ ...scene, index: i + 1 }))
}

const SCENE_CUT_MIN_SEPARATION_SEC = 0.5

/** Cut times are end-of-segment timestamps in seconds; returns segment lengths or null if invalid. */
function computeSegmentDurationsFromCuts(cuts: number[], totalDuration: number): number[] | null {
  if (!Number.isFinite(totalDuration) || totalDuration <= 0) return null
  const sorted = [...cuts].sort((a, b) => a - b)
  if (sorted.some(c => c <= 0 || c >= totalDuration)) return null
  const segments: number[] = []
  if (sorted.length === 0) {
    segments.push(totalDuration)
  } else {
    segments.push(sorted[0])
    for (let i = 1; i < sorted.length; i++) {
      segments.push(sorted[i] - sorted[i - 1])
    }
    segments.push(totalDuration - sorted[sorted.length - 1])
  }
  if (segments.some(d => !Number.isFinite(d) || d <= 0)) return null
  return segments
}

function formatAudioSeconds(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '0.00 s'
  return `${sec.toFixed(2)} s`
}

/** mm:ss for scene narration range labels (pairs with formatAudioSeconds in the timing assistant). */
function formatAudioMmSs(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '00:00'
  const totalSec = Math.floor(sec + 1e-6)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const BACKGROUND_MUSIC_PREVIEW_FILES: Record<
  Exclude<BackgroundMusic, 'none'>,
  string
> = {
  peaceful_piano: 'peaceful_piano.mp3',
  ambient_pad: 'ambient_pad.mp3',
  soft_strings: 'soft_strings.mp3',
  gentle_choir: 'gentle_choir.mp3',
}

function backgroundMusicPreviewUrl(choice: BackgroundMusic): string | null {
  if (choice === 'none') return null
  const file = BACKGROUND_MUSIC_PREVIEW_FILES[choice]
  return `${API_BASE_URL}/assets/music/${file}`
}

type VideoResponse = {
  video_path: string
  video_url: string
  script_text: string
  scenes: Scene[]
  used_ai: boolean
  narration_source?: ManualNarrationSource | null
  narration_audio_path?: string | null
}

type PreviewSceneResponse = {
  preview_video_path: string
  preview_video_url: string
}

type YouTubeAuthStatus = {
  connected: boolean
}

type YouTubeAuthStartResponse = {
  auth_url: string
}

type YouTubePublishResponse = {
  youtube_video_id: string
  youtube_url: string
}

type ExistingSubtitleItem = {
  id: string
  start_seconds: number
  end_seconds: number
  text: string
}

type RenderSubtitlesVideoResponse = {
  video_path: string
  video_url: string
  source_video_path?: string | null
  source_video_url?: string | null
}

type ThemeMode = 'light' | 'dark'

const THEME_STORAGE_KEY = 'sacredclips-theme'

function readStoredTheme(): ThemeMode {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* ignore */
  }
  return 'light'
}

function CollapsibleCard({
  title,
  subtitle,
  defaultOpen = false,
  children,
  className = '',
}: {
  title: string
  subtitle?: string
  defaultOpen?: boolean
  children: React.ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`ui-card collapsible-card ${open ? 'is-open' : 'is-collapsed'} ${className}`}>
      <button
        type="button"
        className="collapsible-card-header"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        <div>
          <h2 className="ui-card-title">{title}</h2>
          {subtitle ? <p className="ui-card-subtitle">{subtitle}</p> : null}
        </div>
        <span className="collapsible-chevron" aria-hidden>
          {open ? '−' : '+'}
        </span>
      </button>
      {open ? <div className="collapsible-card-body">{children}</div> : null}
    </section>
  )
}

function StaticCard({
  title,
  subtitle,
  children,
  className = '',
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={`ui-card ${className}`}>
      <div className="ui-card-header-static">
        <h2 className="ui-card-title">{title}</h2>
        {subtitle ? <p className="ui-card-subtitle">{subtitle}</p> : null}
      </div>
      <div className="ui-card-body">{children}</div>
    </section>
  )
}

export const App: React.FC = () => {
  const [themeMode, setThemeMode] = useState<ThemeMode>(readStoredTheme)
  const [creationMode, setCreationMode] = useState<CreationMode>('ai')
  const [videoType, setVideoType] = useState<VideoType>('normal')
  const [topic, setTopic] = useState(DEFAULT_PROJECT_TOPIC)
  const [style, setStyle] = useState(DEFAULT_PROJECT_STYLE)
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('16:9')
  const [duration, setDuration] = useState(180)
  const [visualStyle, setVisualStyle] = useState<VisualStyle>(DEFAULT_PROJECT_VISUAL_STYLE as VisualStyle)
  const [imageFitMode, setImageFitMode] = useState<ImageFitMode>('fit')
  const [backgroundMusic, setBackgroundMusic] = useState<BackgroundMusic>('none')
  const [backgroundMusicVolume, setBackgroundMusicVolume] = useState(0.12)
  const [motionEffect, setMotionEffect] = useState<MotionEffect>('gentle_zoom')
  const [motionIntensity, setMotionIntensity] = useState<MotionIntensity>('subtle')
  const [subtitleStyle, setSubtitleStyle] = useState<SubtitleStyle>('off')
  const [brandingEnabled, setBrandingEnabled] = useState(false)
  const [brandingLogoPath, setBrandingLogoPath] = useState('')
  const [brandingLogoUrl, setBrandingLogoUrl] = useState('')
  const [brandingLogoPreviewUrl, setBrandingLogoPreviewUrl] = useState('')
  const [brandingPosition, setBrandingPosition] = useState<BrandingPosition>('bottom_right')
  const [brandingSize, setBrandingSize] = useState<BrandingSize>('medium')
  const [brandingOpacity, setBrandingOpacity] = useState(0.8)
  const [brandingUploading, setBrandingUploading] = useState(false)
  const [editedScenes, setEditedScenes] = useState<Scene[]>([])
  const [manualUploads, setManualUploads] = useState<Record<number, File | undefined>>({})
  const [manualImageModes, setManualImageModes] = useState<Record<number, ManualImageMode>>({})
  const [manualNarrationSource, setManualNarrationSource] = useState<ManualNarrationSource>('tts')
  const [manualAudioUpload, setManualAudioUpload] = useState<File | undefined>(undefined)
  /** Server path for uploaded narration; used on JSON regeneration without re-uploading. */
  const [persistedManualNarration, setPersistedManualNarration] = useState<{
    source: 'upload'
    path: string
  } | null>(null)
  /** Post-render manual only: new image files to send via multipart /manual-video. */
  const [replacementUploads, setReplacementUploads] = useState<Record<number, File | undefined>>({})
  const [replacementPreviewUrls, setReplacementPreviewUrls] = useState<Record<number, string>>({})
  const [scenePreviewUrlByIndex, setScenePreviewUrlByIndex] = useState<Record<number, string>>({})
  const [scenePreviewLoadingIndex, setScenePreviewLoadingIndex] = useState<number | null>(null)
  const [scenePreviewNonce, setScenePreviewNonce] = useState(0)
  const [uploadedVideoFile, setUploadedVideoFile] = useState<File | undefined>(undefined)
  const [uploadedVideoUrl, setUploadedVideoUrl] = useState('')
  const [existingSourceVideoPath, setExistingSourceVideoPath] = useState('')
  const [existingSourceVideoUrl, setExistingSourceVideoUrl] = useState('')
  const [existingVideoCurrentTime, setExistingVideoCurrentTime] = useState(0)
  const [activeExistingSubtitlePreviewId, setActiveExistingSubtitlePreviewId] = useState<string | null>(null)
  const [existingSubtitles, setExistingSubtitles] = useState<ExistingSubtitleItem[]>(
    createDefaultExistingSubtitles,
  )
  const [existingVideoLayout, setExistingVideoLayout] = useState<ExistingVideoLayout>(EMPTY_VIDEO_LAYOUT)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const existingVideoPreviewRef = useRef<HTMLVideoElement | null>(null)
  const existingSubtitlePreviewEndRef = useRef<number | null>(null)
  /** Shared element for manual per-scene narration segment preview (upload mode only). */
  const sceneAudioPreviewRef = useRef<HTMLAudioElement | null>(null)
  const sceneSegmentEndRef = useRef<number | null>(null)
  const musicPreviewRef = useRef<HTMLAudioElement | null>(null)
  const [uploadedAudioUrl, setUploadedAudioUrl] = useState('')
  const [uploadedAudioDuration, setUploadedAudioDuration] = useState(0)
  const [uploadedAudioCurrentTime, setUploadedAudioCurrentTime] = useState(0)
  const [sceneCutTimes, setSceneCutTimes] = useState<number[]>([])
  const [activeAudioSceneIndex, setActiveAudioSceneIndex] = useState<number | null>(null)
  const [sceneAudioPreviewPlaying, setSceneAudioPreviewPlaying] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<VideoResponse | null>(null)

  const [editMode, setEditMode] = useState(false)
  const [editedScript, setEditedScript] = useState('')
  const [videoVersion, setVideoVersion] = useState(0) // bump when a new video is ready
  const [copying, setCopying] = useState(false)
  const [copyLabel, setCopyLabel] = useState<'Copy script' | 'Copied!' | 'Copy failed'>('Copy script')

  const [youtubeConnected, setYoutubeConnected] = useState<boolean | null>(null)
  const [youtubeChecking, setYoutubeChecking] = useState(false)
  const [youtubeUploading, setYoutubeUploading] = useState(false)
  const [youtubeError, setYoutubeError] = useState<string | null>(null)
  const [youtubeSuccessUrl, setYoutubeSuccessUrl] = useState<string | null>(null)
  const [youtubeTitle, setYoutubeTitle] = useState('')
  const [youtubeDescription, setYoutubeDescription] = useState('')
  const [youtubePrivacy, setYoutubePrivacy] = useState<'private' | 'unlisted' | 'public'>('unlisted')
  const [generationStage, setGenerationStage] = useState('Idle')
  const [generationProgress, setGenerationProgress] = useState(0)
  const [generationProfile, setGenerationProfile] = useState<GenerationProfile>('ai')
  const [activeRenderJobId, setActiveRenderJobId] = useState<string | null>(null)
  const [renderReconnectNotice, setRenderReconnectNotice] = useState<string | null>(null)
  const [projectSavedAt, setProjectSavedAt] = useState<string | null>(null)
  const [projectResetNotice, setProjectResetNotice] = useState<string | null>(null)
  const jobPollStopRef = useRef<(() => void) | null>(null)
  const draftHydratedRef = useRef(false)
  const autosaveTimerRef = useRef<number | undefined>(undefined)
  const suppressAutosaveRef = useRef(false)
  const projectResetNoticeTimerRef = useRef<number | undefined>(undefined)
  const totalSceneDuration = editedScenes.reduce((acc, s) => acc + (Number.isFinite(s.duration_seconds) ? s.duration_seconds : 0), 0)
  const durationDiff = Math.abs(totalSceneDuration - duration)
  const hasDurationWarning = durationDiff > 10

  const manualSceneAudioRangesByIndex = useMemo(() => {
    const m: Record<number, { start: number; end: number }> = {}
    if (!editedScenes.length) return m
    const sorted = [...editedScenes].sort((a, b) => a.index - b.index)
    let t = 0
    for (const s of sorted) {
      const dur = Number.isFinite(s.duration_seconds) ? Math.max(0, s.duration_seconds) : 0
      m[s.index] = { start: t, end: t + dur }
      t += dur
    }
    return m
  }, [editedScenes])

  const activeExistingSubtitle = useMemo(
    () =>
      existingSubtitles.find(
        s =>
          subtitleStyle !== 'off' &&
          s.text.trim() &&
          existingVideoCurrentTime >= s.start_seconds &&
          existingVideoCurrentTime < s.end_seconds,
      ),
    [existingSubtitles, existingVideoCurrentTime, subtitleStyle],
  )

  const existingVideoPreviewSrc = uploadedVideoUrl || (existingSourceVideoUrl ? `${API_BASE_URL}${existingSourceVideoUrl}` : '')

  const existingVideoPortrait = useMemo(
    () =>
      inferExistingVideoPortrait(
        existingVideoLayout.intrinsicW,
        existingVideoLayout.intrinsicH,
        subtitleStyle,
      ),
    [existingVideoLayout.intrinsicW, existingVideoLayout.intrinsicH, subtitleStyle],
  )

  useEffect(() => {
    if (!existingVideoPreviewSrc) {
      setExistingVideoLayout(EMPTY_VIDEO_LAYOUT)
      return
    }
    const video = existingVideoPreviewRef.current
    if (!video) return

    const onLayoutChange = () => syncExistingVideoLayout(video)
    const observer = new ResizeObserver(onLayoutChange)
    observer.observe(video)
    window.addEventListener('resize', onLayoutChange)
    onLayoutChange()

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', onLayoutChange)
    }
  }, [existingVideoPreviewSrc, videoVersion])

  const durationMin = videoType === 'normal' ? 120 : 60
  const durationMax = videoType === 'normal' ? 600 : 90
  const durationStep = videoType === 'normal' ? 30 : 5

  function brandingApiFields(): Record<string, unknown> {
    if (!brandingEnabled) {
      return { branding_enabled: false }
    }
    return {
      branding_enabled: true,
      ...(brandingLogoPath ? { branding_logo_path: brandingLogoPath } : {}),
      branding_position: brandingPosition,
      branding_size: brandingSize,
      branding_opacity: brandingOpacity,
    }
  }

  function appendBrandingToFormData(fd: FormData) {
    fd.append('branding_enabled', brandingEnabled ? 'true' : 'false')
    if (brandingLogoPath) {
      fd.append('branding_logo_path', brandingLogoPath)
    }
    fd.append('branding_position', brandingPosition)
    fd.append('branding_size', brandingSize)
    fd.append('branding_opacity', String(brandingOpacity))
  }

  const brandingLogoDisplayUrl =
    brandingLogoPreviewUrl ||
    (brandingLogoUrl ? `${API_BASE_URL}${brandingLogoUrl}` : '')

  async function handleBrandingLogoSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const allowed = ['image/png', 'image/jpeg', 'image/webp']
    if (!allowed.includes(file.type)) {
      setError('Logo must be PNG, JPEG, or WebP.')
      return
    }
    setError(null)
    const localPreview = URL.createObjectURL(file)
    setBrandingLogoPreviewUrl(prev => {
      if (prev.startsWith('blob:')) URL.revokeObjectURL(prev)
      return localPreview
    })
    setBrandingUploading(true)
    try {
      const fd = new FormData()
      fd.append('logo', file)
      const res = await fetch(`${API_BASE_URL}/branding/upload`, { method: 'POST', body: fd })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Logo upload failed')
      }
      const data: BrandingUploadResponse = await res.json()
      setBrandingLogoPath(data.branding_logo_path)
      setBrandingLogoUrl(data.branding_logo_url)
      setBrandingEnabled(true)
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Logo upload failed')
      setBrandingLogoPreviewUrl(prev => {
        if (prev.startsWith('blob:')) URL.revokeObjectURL(prev)
        return ''
      })
    } finally {
      setBrandingUploading(false)
    }
  }

  function clearBrandingLogo() {
    setBrandingLogoPath('')
    setBrandingLogoUrl('')
    setBrandingLogoPreviewUrl(prev => {
      if (prev.startsWith('blob:')) URL.revokeObjectURL(prev)
      return ''
    })
  }

  function stopManualSceneAudioPreview() {
    const el = sceneAudioPreviewRef.current
    if (el) {
      el.pause()
      try {
        el.currentTime = 0
      } catch {
        /* ignore */
      }
    }
    sceneSegmentEndRef.current = null
    setActiveAudioSceneIndex(null)
    setSceneAudioPreviewPlaying(false)
  }

  function onScenePreviewAudioTimeUpdate() {
    const el = sceneAudioPreviewRef.current
    const segEnd = sceneSegmentEndRef.current
    if (!el || segEnd == null) return
    if (el.currentTime >= segEnd - 0.04) {
      el.pause()
      sceneSegmentEndRef.current = null
      setActiveAudioSceneIndex(null)
      setSceneAudioPreviewPlaying(false)
    }
  }

  function toggleManualSceneAudioPreview(sceneIndex: number) {
    const range = manualSceneAudioRangesByIndex[sceneIndex]
    const el = sceneAudioPreviewRef.current
    if (!range || !uploadedAudioUrl || !el) return

    if (activeAudioSceneIndex === sceneIndex && sceneAudioPreviewPlaying) {
      stopManualSceneAudioPreview()
      return
    }

    const assistant = audioRef.current
    if (assistant && !assistant.paused) assistant.pause()

    el.pause()
    const { start, end } = range
    sceneSegmentEndRef.current = end
    el.currentTime = start
    const playPromise = el.play()
    if (playPromise !== undefined) {
      playPromise
        .then(() => {
          setActiveAudioSceneIndex(sceneIndex)
          setSceneAudioPreviewPlaying(true)
        })
        .catch(() => {
          sceneSegmentEndRef.current = null
          setActiveAudioSceneIndex(null)
          setSceneAudioPreviewPlaying(false)
        })
    } else {
      setActiveAudioSceneIndex(sceneIndex)
      setSceneAudioPreviewPlaying(true)
    }
  }

  function stopExistingSubtitlePreview() {
    const el = existingVideoPreviewRef.current
    if (el) el.pause()
    existingSubtitlePreviewEndRef.current = null
    setActiveExistingSubtitlePreviewId(null)
  }

  function syncExistingVideoLayout(el?: HTMLVideoElement | null) {
    const video = el ?? existingVideoPreviewRef.current
    if (!video) return
    setExistingVideoLayout({
      intrinsicW: video.videoWidth || 0,
      intrinsicH: video.videoHeight || 0,
      displayW: video.clientWidth || 0,
      displayH: video.clientHeight || 0,
    })
  }

  function syncExistingVideoPreviewTime(el: HTMLVideoElement) {
    syncExistingVideoLayout(el)
    setExistingVideoCurrentTime(el.currentTime)
    const end = existingSubtitlePreviewEndRef.current
    if (end != null && el.currentTime >= end - 0.04) {
      el.pause()
      existingSubtitlePreviewEndRef.current = null
      setActiveExistingSubtitlePreviewId(null)
    }
  }

  function toggleExistingSubtitlePreview(item: ExistingSubtitleItem) {
    const el = existingVideoPreviewRef.current
    if (!el || !existingVideoPreviewSrc) return

    if (activeExistingSubtitlePreviewId === item.id) {
      stopExistingSubtitlePreview()
      return
    }

    const start = Math.max(0, item.start_seconds)
    const end = Math.max(start, item.end_seconds)
    if (end <= start + 0.04) return

    el.pause()
    existingSubtitlePreviewEndRef.current = end
    el.currentTime = start
    setExistingVideoCurrentTime(start)
    const playPromise = el.play()
    if (playPromise !== undefined) {
      playPromise
        .then(() => setActiveExistingSubtitlePreviewId(item.id))
        .catch(() => {
          existingSubtitlePreviewEndRef.current = null
          setActiveExistingSubtitlePreviewId(null)
        })
    } else {
      setActiveExistingSubtitlePreviewId(item.id)
    }
  }

  const beginGenerationProgress = (profile: GenerationProfile) => {
    setGenerationProfile(profile)
    setGenerationStage('Preparing request')
    setGenerationProgress(5)
    setRenderReconnectNotice(null)
  }

  const finishGenerationProgress = async () => {
    setGenerationStage('Complete')
    setGenerationProgress(100)
    await new Promise(resolve => setTimeout(resolve, 250))
  }

  const stopJobPolling = () => {
    jobPollStopRef.current?.()
    jobPollStopRef.current = null
  }

  const collectProjectDraft = useCallback((): ProjectDraft => {
    return {
      version: DRAFT_VERSION,
      savedAt: new Date().toISOString(),
      creationMode,
      topic,
      style,
      videoType,
      duration,
      aspectRatio,
      imageFitMode,
      visualStyle,
      editedScript,
      editedScenes,
      manualImageModes,
      manualNarrationSource,
      persistedManualNarration,
      existingSubtitles,
      existingSourceVideoPath,
      existingSourceVideoUrl,
      backgroundMusic,
      backgroundMusicVolume,
      motionEffect,
      motionIntensity,
      subtitleStyle,
      brandingEnabled,
      brandingLogoPath,
      brandingLogoUrl,
      brandingPosition,
      brandingSize,
      brandingOpacity,
      activeRenderJobId,
      latestResult: result
        ? {
            video_path: result.video_path,
            video_url: result.video_url,
            script_text: result.script_text,
            scenes: result.scenes,
            used_ai: result.used_ai,
            narration_source: result.narration_source ?? null,
            narration_audio_path: result.narration_audio_path ?? null,
          }
        : null,
      editMode,
    }
  }, [
    creationMode,
    topic,
    style,
    videoType,
    duration,
    aspectRatio,
    imageFitMode,
    visualStyle,
    editedScript,
    editedScenes,
    manualImageModes,
    manualNarrationSource,
    persistedManualNarration,
    existingSubtitles,
    existingSourceVideoPath,
    existingSourceVideoUrl,
    backgroundMusic,
    backgroundMusicVolume,
    motionEffect,
    motionIntensity,
    subtitleStyle,
    brandingEnabled,
    brandingLogoPath,
    brandingLogoUrl,
    brandingPosition,
    brandingSize,
    brandingOpacity,
    activeRenderJobId,
    result,
    editMode,
  ])

  const persistProjectDraft = useCallback(
    (patch?: Partial<ProjectDraft>) => {
      const draft = { ...collectProjectDraft(), ...patch, savedAt: new Date().toISOString() }
      if (saveProjectDraft(draft)) {
        setProjectSavedAt(draft.savedAt)
      }
    },
    [collectProjectDraft],
  )

  const applyVideoResponse = useCallback(
    (data: VideoResponse, options?: { clearManualUploads?: boolean }) => {
      setResult(data)
      setEditedScript(data.script_text)
      setEditedScenes(data.scenes)
      setVideoVersion(prev => prev + 1)
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
      if (options?.clearManualUploads !== false) {
        setManualUploads({})
        setManualImageModes({})
        setManualAudioUpload(undefined)
      }
      setPersistedManualNarration(
        data.narration_source === 'upload' && data.narration_audio_path
          ? { source: 'upload', path: data.narration_audio_path }
          : null,
      )
      persistProjectDraft({
        latestResult: {
          video_path: data.video_path,
          video_url: data.video_url,
          script_text: data.script_text,
          scenes: data.scenes,
          used_ai: data.used_ai,
          narration_source: data.narration_source ?? null,
          narration_audio_path: data.narration_audio_path ?? null,
        },
        activeRenderJobId: null,
      })
    },
    [persistProjectDraft, topic],
  )

  const applySubtitlesResponse = useCallback(
    (data: RenderSubtitlesVideoResponse, scriptText: string) => {
      setExistingSourceVideoPath(data.source_video_path || existingSourceVideoPath)
      setExistingSourceVideoUrl(data.source_video_url || existingSourceVideoUrl)
      const nextResult: VideoResponse = {
        video_path: data.video_path,
        video_url: data.video_url,
        script_text: scriptText || 'Existing video with subtitles.',
        scenes: [],
        used_ai: false,
        narration_source: null,
        narration_audio_path: null,
      }
      setResult(nextResult)
      setVideoVersion(prev => prev + 1)
      setYoutubeTitle(topic)
      setYoutubeDescription(scriptText)
      persistProjectDraft({
        existingSourceVideoPath: data.source_video_path || existingSourceVideoPath,
        existingSourceVideoUrl: data.source_video_url || existingSourceVideoUrl,
        latestResult: {
          video_path: nextResult.video_path,
          video_url: nextResult.video_url,
          script_text: nextResult.script_text,
          scenes: [],
          used_ai: false,
          narration_source: null,
          narration_audio_path: null,
        },
        activeRenderJobId: null,
      })
    },
    [existingSourceVideoPath, existingSourceVideoUrl, persistProjectDraft, topic],
  )

  const handleRenderJobUpdate = useCallback((job: RenderJobStatus) => {
    setGenerationStage(formatJobStage(job.stage))
    setGenerationProgress(job.progress)
  }, [])

  const startRenderJobPolling = useCallback(
    (
      jobId: string,
      profile: GenerationProfile,
      onSuccess: (result: Record<string, unknown>) => void | Promise<void>,
    ) => {
      stopJobPolling()
      setGenerationProfile(profile)
      setActiveRenderJobId(jobId)
      setLoading(true)
      persistProjectDraft({ activeRenderJobId: jobId })

      jobPollStopRef.current = pollRenderJob(API_BASE_URL, jobId, {
        onUpdate: handleRenderJobUpdate,
        onComplete: async job => {
          stopJobPolling()
          setActiveRenderJobId(null)
          await finishGenerationProgress()
          if (job.result) {
            await onSuccess(job.result)
          }
          setLoading(false)
        },
        onFailed: job => {
          stopJobPolling()
          setActiveRenderJobId(null)
          setError(job.error || 'Render failed')
          persistProjectDraft({ activeRenderJobId: null })
          setLoading(false)
        },
        onError: err => {
          console.warn('Job poll error (will retry):', err.message)
        },
      })
    },
    [handleRenderJobUpdate, persistProjectDraft],
  )

  const resumeRenderJobIfNeeded = useCallback(
    async (jobId: string, showNotice = false) => {
      try {
        const job = await fetchRenderJob(API_BASE_URL, jobId)
        handleRenderJobUpdate(job)
        if (job.status === 'completed' && job.result) {
          stopJobPolling()
          setActiveRenderJobId(null)
          setLoading(false)
          if (job.job_type === 'render_subtitles') {
            const scriptText = existingSubtitles.map(s => s.text.trim()).filter(Boolean).join('\n')
            applySubtitlesResponse(job.result as unknown as RenderSubtitlesVideoResponse, scriptText)
          } else {
            applyVideoResponse(job.result as unknown as VideoResponse, { clearManualUploads: false })
          }
          if (showNotice) {
            setRenderReconnectNotice('Render completed while you were away. Result restored.')
          }
          return
        }
        if (job.status === 'failed') {
          stopJobPolling()
          setActiveRenderJobId(null)
          setLoading(false)
          setError(job.error || 'Render failed')
          return
        }
        if (job.status === 'queued' || job.status === 'running') {
          setLoading(true)
          if (showNotice) {
            setRenderReconnectNotice('Render still running on the backend. Reconnected successfully.')
          }
          if (jobPollStopRef.current) {
            return
          }
          const profile: GenerationProfile =
            job.job_type === 'render_subtitles'
              ? 'subtitles'
              : job.job_type === 'manual_video'
                ? 'manual_tts'
                : job.job_type === 'regenerate'
                  ? 'regenerate'
                  : 'ai'
          startRenderJobPolling(jobId, profile, async result => {
            if (job.job_type === 'render_subtitles') {
              const scriptText = existingSubtitles.map(s => s.text.trim()).filter(Boolean).join('\n')
              applySubtitlesResponse(result as unknown as RenderSubtitlesVideoResponse, scriptText)
            } else {
              applyVideoResponse(result as unknown as VideoResponse, { clearManualUploads: false })
            }
          })
        }
      } catch (err: unknown) {
        console.warn('Could not resume render job', err)
      }
    },
    [
      applySubtitlesResponse,
      applyVideoResponse,
      existingSubtitles,
      handleRenderJobUpdate,
      startRenderJobPolling,
    ],
  )

  const clearReplacementUploadState = () => {
    setReplacementPreviewUrls(prev => {
      Object.values(prev).forEach(u => {
        try {
          URL.revokeObjectURL(u)
        } catch {
          /* ignore */
        }
      })
      return {}
    })
    setReplacementUploads({})
  }

  const clearScenePreviews = () => {
    setScenePreviewUrlByIndex({})
    setScenePreviewLoadingIndex(null)
  }

  const clearExistingVideoResult = () => {
    if (creationMode === 'existing') {
      setResult(null)
      setYoutubeSuccessUrl(null)
      setYoutubeError(null)
      setVideoVersion(0)
    }
  }

  const updateExistingSubtitle = (id: string, patch: Partial<ExistingSubtitleItem>) => {
    stopExistingSubtitlePreview()
    setExistingSubtitles(prev => prev.map(s => (s.id === id ? { ...s, ...patch } : s)))
    clearExistingVideoResult()
  }

  const addExistingSubtitle = () => {
    stopExistingSubtitlePreview()
    setExistingSubtitles(prev => {
      const last = prev[prev.length - 1]
      const start = last ? Math.max(0, last.end_seconds) : 0
      return [
        ...prev,
        {
          id: `subtitle-${Date.now()}`,
          start_seconds: start,
          end_seconds: start + DEFAULT_EXISTING_SUBTITLE_DURATION_SEC,
          text: 'New subtitle',
        },
      ]
    })
    clearExistingVideoResult()
  }

  const duplicateExistingSubtitle = (id: string) => {
    stopExistingSubtitlePreview()
    setExistingSubtitles(prev => {
      const idx = prev.findIndex(s => s.id === id)
      if (idx < 0) return prev
      const source = prev[idx]
      const dup = {
        ...source,
        id: `subtitle-${Date.now()}`,
        start_seconds: source.end_seconds,
        end_seconds: source.end_seconds + Math.max(0.5, source.end_seconds - source.start_seconds),
      }
      return [...prev.slice(0, idx + 1), dup, ...prev.slice(idx + 1)]
    })
    clearExistingVideoResult()
  }

  const removeExistingSubtitle = (id: string) => {
    stopExistingSubtitlePreview()
    setExistingSubtitles(prev => (prev.length <= 1 ? prev : prev.filter(s => s.id !== id)))
    clearExistingVideoResult()
  }

  const handleExistingVideoFileChange = (file: File | undefined) => {
    stopExistingSubtitlePreview()
    setUploadedVideoFile(file)
    setExistingSourceVideoPath('')
    setExistingSourceVideoUrl('')
    setExistingVideoCurrentTime(0)
    setExistingVideoLayout(EMPTY_VIDEO_LAYOUT)
    clearExistingVideoResult()
  }

  const updateReplacementUploadForScene = (sceneIndex: number, file: File | undefined) => {
    setReplacementPreviewUrls(prev => {
      const old = prev[sceneIndex]
      if (old) {
        try {
          URL.revokeObjectURL(old)
        } catch {
          /* ignore */
        }
      }
      const next = { ...prev }
      if (!file) delete next[sceneIndex]
      else next[sceneIndex] = URL.createObjectURL(file)
      return next
    })
    setReplacementUploads(prev => {
      const next = { ...prev }
      if (!file) delete next[sceneIndex]
      else next[sceneIndex] = file
      return next
    })
  }

  const updateManualUploadForScene = (sceneIndex: number, file: File | undefined) => {
    setManualUploads(prev => ({ ...prev, [sceneIndex]: file }))
    clearScenePreviews()
  }

  const resetToNewVideo = () => {
    if (
      !window.confirm(
        'Start a new video? This clears your saved local project draft and any in-progress render tracking.',
      )
    ) {
      return
    }
    stopJobPolling()
    clearProjectDraft()
    setProjectSavedAt(null)
    setActiveRenderJobId(null)
    setRenderReconnectNotice(null)
    stopManualSceneAudioPreview()
    stopExistingSubtitlePreview()
    setResult(null)
    setEditedScript('')
    setEditedScenes([])
    setManualUploads({})
    setManualImageModes({})
    setManualAudioUpload(undefined)
    setUploadedVideoFile(undefined)
    setUploadedVideoUrl('')
    setExistingSourceVideoPath('')
    setExistingSourceVideoUrl('')
    setExistingVideoCurrentTime(0)
    setActiveExistingSubtitlePreviewId(null)
    setExistingVideoLayout(EMPTY_VIDEO_LAYOUT)
    setExistingSubtitles([
      {
        id: 'subtitle-1',
        start_seconds: 0,
        end_seconds: DEFAULT_EXISTING_SUBTITLE_DURATION_SEC,
        text: "Welcome to today's lesson.",
      },
    ])
    setPersistedManualNarration(null)
    clearReplacementUploadState()
    clearScenePreviews()
    setVideoVersion(0)
    setYoutubeSuccessUrl(null)
    setYoutubeError(null)
    setError(null)
    setEditMode(false)
    setLoading(false)
    setGenerationStage('Idle')
    setGenerationProgress(0)
  }

  const applyDefaultProjectState = () => {
    stopManualSceneAudioPreview()
    stopExistingSubtitlePreview()

    setCreationMode('ai')
    setVideoType('normal')
    setTopic(DEFAULT_PROJECT_TOPIC)
    setStyle(DEFAULT_PROJECT_STYLE)
    setAspectRatio('16:9')
    setDuration(180)
    setVisualStyle(DEFAULT_PROJECT_VISUAL_STYLE as VisualStyle)
    setImageFitMode('fit')
    setBackgroundMusic('none')
    setBackgroundMusicVolume(0.12)
    setMotionEffect('gentle_zoom')
    setMotionIntensity('subtle')
    setSubtitleStyle('off')

    setBrandingEnabled(false)
    setBrandingLogoPath('')
    setBrandingLogoUrl('')
    setBrandingLogoPreviewUrl(prev => {
      if (prev.startsWith('blob:')) URL.revokeObjectURL(prev)
      return ''
    })
    setBrandingPosition('bottom_right')
    setBrandingSize('medium')
    setBrandingOpacity(0.8)
    setBrandingUploading(false)

    setEditedScript('')
    setEditedScenes([])
    setManualUploads({})
    setManualImageModes({})
    setManualNarrationSource('tts')
    setManualAudioUpload(undefined)
    setPersistedManualNarration(null)
    clearReplacementUploadState()
    clearScenePreviews()
    setScenePreviewNonce(0)

    setUploadedVideoFile(undefined)
    setUploadedVideoUrl('')
    setExistingSourceVideoPath('')
    setExistingSourceVideoUrl('')
    setExistingVideoCurrentTime(0)
    setActiveExistingSubtitlePreviewId(null)
    setExistingVideoLayout(EMPTY_VIDEO_LAYOUT)
    setExistingSubtitles(createDefaultExistingSubtitles())

    setUploadedAudioUrl('')
    setUploadedAudioDuration(0)
    setUploadedAudioCurrentTime(0)
    setSceneCutTimes([])
    setActiveAudioSceneIndex(null)
    setSceneAudioPreviewPlaying(false)

    setResult(null)
    setEditMode(false)
    setVideoVersion(0)
    setCopying(false)
    setCopyLabel('Copy script')

    setYoutubeTitle('')
    setYoutubeDescription('')
    setYoutubeSuccessUrl(null)
    setYoutubeError(null)

    setLoading(false)
    setError(null)
    setGenerationStage('Idle')
    setGenerationProgress(0)
    setGenerationProfile('ai')
    setActiveRenderJobId(null)
    setRenderReconnectNotice(null)
  }

  const handleClearSavedProject = () => {
    if (
      !window.confirm(
        'Clear the saved project and reset all project data and settings? This cannot be undone.',
      )
    ) {
      return
    }

    suppressAutosaveRef.current = true
    if (autosaveTimerRef.current !== undefined) {
      window.clearTimeout(autosaveTimerRef.current)
      autosaveTimerRef.current = undefined
    }
    if (projectResetNoticeTimerRef.current !== undefined) {
      window.clearTimeout(projectResetNoticeTimerRef.current)
    }

    stopJobPolling()
    clearProjectDraft()
    applyDefaultProjectState()
    setProjectSavedAt(null)

    setProjectResetNotice('Saved project cleared. SacredClips has been reset to its default state.')
    projectResetNoticeTimerRef.current = window.setTimeout(() => {
      setProjectResetNotice(null)
      projectResetNoticeTimerRef.current = undefined
    }, 6000)

    window.setTimeout(() => {
      suppressAutosaveRef.current = false
    }, 0)
  }

  const startRenderJobRequest = async (
    endpoint: string,
    init: RequestInit,
    profile: GenerationProfile,
    onSuccess: (result: Record<string, unknown>) => void | Promise<void>,
  ) => {
    const res = await fetch(`${API_BASE_URL}${endpoint}`, init)
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || 'Failed to start render job')
    }
    const data = (await res.json()) as { job_id: string }
    startRenderJobPolling(data.job_id, profile, onSuccess)
  }

  const handleAiGenerate = async () => {
    beginGenerationProgress('ai')
    setError(null)
    setResult(null)
    setPersistedManualNarration(null)
    clearReplacementUploadState()
    setEditMode(false)
    setLoading(true)
    setYoutubeError(null)
    setYoutubeSuccessUrl(null)
    try {
      await startRenderJobRequest(
        '/jobs/generate-video',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            topic,
            style,
            duration_seconds: duration,
            visual_style: visualStyle,
            aspect_ratio: aspectRatio,
            image_fit_mode: imageFitMode,
            background_music: backgroundMusic,
            background_music_volume: backgroundMusicVolume,
            motion_effect: motionEffect,
            motion_intensity: motionIntensity,
            subtitle_style: subtitleStyle,
            ...brandingApiFields(),
          }),
        },
        'ai',
        async result => {
          applyVideoResponse(result as unknown as VideoResponse)
          setEditMode(false)
          clearScenePreviews()
        },
      )
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
      setLoading(false)
    }
  }

  const handleManualCreate = async () => {
    if (manualNarrationSource === 'tts' && !editedScript.trim()) {
      setError('Paste a script (narration) for manual mode.')
      return
    }
    if (manualNarrationSource === 'upload' && !manualAudioUpload) {
      setError('Select an audio file for uploaded narration mode.')
      return
    }
    if (!editedScenes.length) {
      setError('Split your script into at least one scene, or edit scene cards.')
      return
    }
    setError(null)
    setResult(null)
    clearReplacementUploadState()
    beginGenerationProgress(manualNarrationSource === 'upload' ? 'manual_upload' : 'manual_tts')
    setLoading(true)
    stopManualSceneAudioPreview()
    setYoutubeError(null)
    setYoutubeSuccessUrl(null)
    try {
      const fallbackTimelineScript = editedScenes
        .map(s => s.text.trim())
        .filter(Boolean)
        .join('\n\n')
      const effectiveScriptText = editedScript.trim()
        || fallbackTimelineScript
        || 'Manual video with uploaded narration.'
      const safeScenesPayload = sanitizeScenesForPayload(editedScenes)

      const fd = new FormData()
      fd.append('topic', topic)
      fd.append('script_text', effectiveScriptText)
      fd.append('scenes_json', JSON.stringify(safeScenesPayload))
      fd.append('visual_style', visualStyle)
      fd.append('duration_seconds', String(duration))
      fd.append('style', style)
      fd.append('aspect_ratio', aspectRatio)
      fd.append('image_fit_mode', imageFitMode)
      fd.append('background_music', backgroundMusic)
      fd.append('background_music_volume', String(backgroundMusicVolume))
      fd.append('motion_effect', motionEffect)
      fd.append('motion_intensity', motionIntensity)
      fd.append('subtitle_style', subtitleStyle)
      fd.append('narration_source', manualNarrationSource)
      appendBrandingToFormData(fd)
      if (manualNarrationSource === 'upload' && manualAudioUpload) {
        fd.append('audio_upload', manualAudioUpload)
      }

      for (const s of editedScenes) {
        const file = manualUploads[s.index]
        const selectedMode = manualImageModes[s.index] ?? (file ? 'upload' : 'placeholder')
        fd.append(`scene_image_mode_${s.index}`, selectedMode)
        if (file) {
          // Must match backend multipart key parsed in /manual-video.
          fd.append(`scene_upload_${s.index}`, file)
        }
      }

      await startRenderJobRequest(
        '/jobs/manual-video',
        { method: 'POST', body: fd },
        manualNarrationSource === 'upload' ? 'manual_upload' : 'manual_tts',
        async result => {
          applyVideoResponse(result as unknown as VideoResponse)
          setEditMode(false)
          clearScenePreviews()
        },
      )
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
      setLoading(false)
    }
  }

  const handleRenderExistingVideoSubtitles = async () => {
    if (!uploadedVideoFile && !existingSourceVideoPath) {
      setError('Upload an existing video first.')
      return
    }
    const cleanSubtitles = existingSubtitles
      .map(s => ({
        ...s,
        start_seconds: Number.isFinite(s.start_seconds) ? Math.max(0, s.start_seconds) : 0,
        end_seconds: Number.isFinite(s.end_seconds) ? Math.max(0, s.end_seconds) : 0,
        text: s.text.trim(),
      }))
      .filter(s => s.text && s.end_seconds > s.start_seconds)
    if (subtitleStyle !== 'off' && cleanSubtitles.length === 0) {
      setError('Add at least one valid subtitle segment, or set subtitles to Off.')
      return
    }
    setError(null)
    setResult(null)
    beginGenerationProgress('subtitles')
    setLoading(true)
    stopExistingSubtitlePreview()
    setYoutubeError(null)
    setYoutubeSuccessUrl(null)
    try {
      const fd = new FormData()
      fd.append('topic', topic)
      fd.append('subtitle_style', subtitleStyle)
      fd.append('subtitles_json', JSON.stringify(cleanSubtitles))
      appendBrandingToFormData(fd)
      if (existingSourceVideoPath) {
        fd.append('source_video_path', existingSourceVideoPath)
      } else if (uploadedVideoFile) {
        fd.append('video_upload', uploadedVideoFile)
      }

      const scriptText = cleanSubtitles.map(s => s.text).join('\n')
      await startRenderJobRequest(
        '/jobs/render-subtitles-video',
        { method: 'POST', body: fd },
        'subtitles',
        async result => {
          applySubtitlesResponse(result as unknown as RenderSubtitlesVideoResponse, scriptText)
        },
      )
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Subtitle render failed')
      setLoading(false)
    }
  }

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (creationMode === 'ai') handleAiGenerate()
    else if (creationMode === 'manual') handleManualCreate()
    else handleRenderExistingVideoSubtitles()
  }

  const handleRebuildFromScenes = async () => {
    if (!result || !editedScenes.length) return
    const timelineScript = editedScenes
      .map(s => s.text.trim())
      .filter(Boolean)
      .join('\n\n')
    if (!timelineScript) {
      setError('Scene text is empty. Add narration text to at least one scene before regenerating.')
      return
    }
    setError(null)
    beginGenerationProgress('regenerate')
    setLoading(true)
    setYoutubeError(null)
    setYoutubeSuccessUrl(null)
    try {
      const hasReplacementFiles =
        !result.used_ai && editedScenes.some(s => Boolean(replacementUploads[s.index]))

      const onRebuildSuccess = async (data: VideoResponse) => {
        applyVideoResponse(data, { clearManualUploads: true })
        setEditMode(false)
        clearReplacementUploadState()
        clearScenePreviews()
      }

      if (hasReplacementFiles) {
        const safeScenesPayload = sanitizeScenesForPayload(editedScenes)
        const fd = new FormData()
        fd.append('topic', topic)
        fd.append('script_text', timelineScript)
        fd.append('scenes_json', JSON.stringify(safeScenesPayload))
        fd.append('visual_style', visualStyle)
        fd.append('duration_seconds', String(duration))
        fd.append('style', style)
        fd.append('aspect_ratio', aspectRatio)
        fd.append('image_fit_mode', imageFitMode)
        fd.append('background_music', backgroundMusic)
        fd.append('background_music_volume', String(backgroundMusicVolume))
        fd.append('motion_effect', motionEffect)
        fd.append('motion_intensity', motionIntensity)
        fd.append('subtitle_style', subtitleStyle)
        appendBrandingToFormData(fd)

        if (persistedManualNarration) {
          fd.append('narration_source', 'upload')
          fd.append('narration_audio_path', persistedManualNarration.path)
        } else {
          fd.append('narration_source', 'tts')
        }

        for (const s of editedScenes) {
          const rep = replacementUploads[s.index]
          if (rep) {
            fd.append(`scene_image_mode_${s.index}`, 'upload')
            fd.append(`scene_upload_${s.index}`, rep)
          } else {
            const mode: ManualImageMode =
              s.image_mode ?? (s.image_path ? 'upload' : 'placeholder')
            fd.append(`scene_image_mode_${s.index}`, mode)
          }
        }

        await startRenderJobRequest(
          '/jobs/manual-video',
          { method: 'POST', body: fd },
          'regenerate',
          async result => {
            await onRebuildSuccess(result as unknown as VideoResponse)
          },
        )
      } else {
        const narrationPayload: Record<string, string> = {}
        if (!result.used_ai) {
          if (persistedManualNarration) {
            narrationPayload.narration_source = 'upload'
            narrationPayload.narration_audio_path = persistedManualNarration.path
          } else {
            narrationPayload.narration_source = 'tts'
          }
        }

        await startRenderJobRequest(
          '/jobs/regenerate-video',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              topic,
              style,
              duration_seconds: duration,
              script_text: timelineScript,
              scenes: scenesForApiPayload(editedScenes),
              visual_style: visualStyle,
              aspect_ratio: aspectRatio,
              image_fit_mode: imageFitMode,
              background_music: backgroundMusic,
              background_music_volume: backgroundMusicVolume,
              motion_effect: motionEffect,
              motion_intensity: motionIntensity,
              subtitle_style: subtitleStyle,
              ...narrationPayload,
              ...brandingApiFields(),
            }),
          },
          'regenerate',
          async result => {
            await onRebuildSuccess(result as unknown as VideoResponse)
          },
        )
      }
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
      setLoading(false)
    }
  }

  const handlePreviewScene = async (sceneIndex: number) => {
    if (!editedScenes.length) return
    const timelineScript = editedScenes
      .map(s => s.text.trim())
      .filter(Boolean)
      .join('\n\n')
    setError(null)
    setScenePreviewLoadingIndex(sceneIndex)
    try {
      const preRenderManualPreview = creationMode === 'manual' && !result
      const narrationSource = preRenderManualPreview
        ? manualNarrationSource
        : persistedManualNarration
          ? ('upload' as const)
          : ('tts' as const)
      const payload = {
        topic,
        scene_index: sceneIndex,
        style,
        script_text: timelineScript.trim().length ? timelineScript : 'Preview',
        scenes: preRenderManualPreview
          ? sanitizeScenesForPayload(
              editedScenes.map(s => ({
                ...s,
                image_mode: manualImageModes[s.index] ?? (manualUploads[s.index] ? 'upload' : 'placeholder'),
              })),
            )
          : scenesForApiPayload(editedScenes),
        visual_style: visualStyle,
        aspect_ratio: aspectRatio,
        image_fit_mode: imageFitMode,
        background_music: backgroundMusic,
        background_music_volume: backgroundMusicVolume,
        motion_effect: motionEffect,
        motion_intensity: motionIntensity,
        subtitle_style: subtitleStyle,
        narration_source: narrationSource,
        narration_audio_path: preRenderManualPreview ? undefined : persistedManualNarration?.path,
      }
      const rep = replacementUploads[sceneIndex]
      const manualUpload = preRenderManualPreview ? manualUploads[sceneIndex] : undefined
      let res: Response
      if (preRenderManualPreview) {
        stopManualSceneAudioPreview()
        const fd = new FormData()
        fd.append('payload', JSON.stringify(payload))
        if (manualNarrationSource === 'upload' && manualAudioUpload) {
          fd.append('audio_upload', manualAudioUpload)
        }
        if (manualUpload) {
          fd.append('preview_image', manualUpload)
        }
        res = await fetch(`${API_BASE_URL}/preview-scene`, { method: 'POST', body: fd })
      } else if (rep) {
        const fd = new FormData()
        fd.append('payload', JSON.stringify(payload))
        fd.append('preview_image', rep)
        res = await fetch(`${API_BASE_URL}/preview-scene`, { method: 'POST', body: fd })
      } else {
        res = await fetch(`${API_BASE_URL}/preview-scene`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
      }
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Preview failed')
      }
      const data: PreviewSceneResponse = await res.json()
      setScenePreviewUrlByIndex(prev => ({ ...prev, [sceneIndex]: data.preview_video_url }))
      setScenePreviewNonce(n => n + 1)
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Scene preview failed')
    } finally {
      setScenePreviewLoadingIndex(null)
    }
  }

  const handleCreationModeChange = (m: CreationMode) => {
    setCreationMode(m)
    setError(null)
    setResult(null)
    setYoutubeSuccessUrl(null)
    setYoutubeError(null)
    if (m === 'manual' && !result) {
      setEditedScenes(prev =>
        prev.length
          ? prev
          : [
              {
                index: 1,
                text: '',
                keywords: ['manual scene'],
                duration_seconds: roundToHalfSecond(Math.max(15, duration / 4)),
              },
            ],
      )
    }
  }

  const handleVideoTypeChange = (nextType: VideoType) => {
    setVideoType(nextType)
    if (nextType === 'normal') {
      setAspectRatio('16:9')
      setImageFitMode('fit')
      setDuration(prev => (prev < 120 || prev > 600 ? 180 : prev))
    } else {
      setAspectRatio('9:16')
      setImageFitMode('fill')
      setDuration(prev => (prev < 60 || prev > 90 ? 60 : prev))
    }
  }

  const updateScene = (sceneIndex: number, patch: Partial<Scene>) => {
    setEditedScenes(prev => prev.map(sc => (sc.index === sceneIndex ? { ...sc, ...patch } : sc)))
    clearScenePreviews()
  }

  const addManualScene = () => {
    stopManualSceneAudioPreview()
    clearScenePreviews()
    const base = reindexScenes(editedScenes)
    setEditedScenes([
      ...base,
      {
        index: base.length + 1,
        text: 'Manual visual scene',
        keywords: ['manual scene'],
        duration_seconds: 10,
        image_url: null,
      },
    ])
  }

  const removeManualScene = (sceneIndex: number) => {
    stopManualSceneAudioPreview()
    clearScenePreviews()
    if (editedScenes.length <= 1) return
    const filteredOld = editedScenes.filter(s => s.index !== sceneIndex)
    const reindexed = reindexScenes(filteredOld)
    const indexMap = new Map<number, number>()
    filteredOld.forEach((scene, i) => indexMap.set(scene.index, reindexed[i].index))
    const nextUploads: Record<number, File | undefined> = {}
    const nextModes: Record<number, ManualImageMode> = {}
    indexMap.forEach((newIdx, oldIdx) => {
      if (manualUploads[oldIdx]) nextUploads[newIdx] = manualUploads[oldIdx]
      if (manualImageModes[oldIdx]) nextModes[newIdx] = manualImageModes[oldIdx]
    })
    setEditedScenes(reindexed)
    setManualUploads(nextUploads)
    setManualImageModes(nextModes)
  }

  const duplicateManualScene = (sceneIndex: number) => {
    stopManualSceneAudioPreview()
    clearScenePreviews()
    const idx = editedScenes.findIndex(s => s.index === sceneIndex)
    if (idx < 0) return
    const source = editedScenes[idx]
    const duplicate: Scene = {
      ...source,
      image_url: null,
    }
    const nextRaw = [...editedScenes]
    nextRaw.splice(idx + 1, 0, duplicate)
    const reindexed = reindexScenes(nextRaw)
    const indexMap = new Map<number, number>()
    editedScenes.forEach((scene, i) => {
      const newPos = i <= idx ? i : i + 1
      indexMap.set(scene.index, reindexed[newPos].index)
    })
    const nextUploads: Record<number, File | undefined> = {}
    const nextModes: Record<number, ManualImageMode> = {}
    indexMap.forEach((newIdx, oldIdx) => {
      if (manualUploads[oldIdx]) nextUploads[newIdx] = manualUploads[oldIdx]
      if (manualImageModes[oldIdx]) nextModes[newIdx] = manualImageModes[oldIdx]
    })
    // For duplicated scene: keep same image mode if available, but no uploaded file.
    const sourceMode = manualImageModes[source.index]
    if (sourceMode) nextModes[reindexed[idx + 1].index] = sourceMode
    setEditedScenes(reindexed)
    setManualUploads(nextUploads)
    setManualImageModes(nextModes)
  }

  const moveScene = (sceneIndex: number, direction: 'up' | 'down') => {
    setEditedScenes(prev => {
      const currentIdx = prev.findIndex(sc => sc.index === sceneIndex)
      if (currentIdx < 0) return prev
      const targetIdx = direction === 'up' ? currentIdx - 1 : currentIdx + 1
      if (targetIdx < 0 || targetIdx >= prev.length) return prev

      const copy = [...prev]
      const [moved] = copy.splice(currentIdx, 1)
      copy.splice(targetIdx, 0, moved)
      return copy.map((scene, i) => ({ ...scene, index: i + 1 }))
    })
    clearReplacementUploadState()
    clearScenePreviews()
  }

  /** Post-generation timeline: insert a blank placeholder scene after this index and reindex. */
  const addSceneAfter = (sceneIndex: number) => {
    setEditedScenes(prev => {
      const idx = prev.findIndex(s => s.index === sceneIndex)
      if (idx < 0) return prev
      const cur = prev[idx]
      let updatedCur: Scene = { ...cur }
      let newSceneDuration = 3
      if (cur.duration_seconds > 2) {
        const half = roundToHalfSecond(cur.duration_seconds / 2)
        const rest = roundToHalfSecond(Math.max(0.5, cur.duration_seconds - half))
        updatedCur = { ...cur, duration_seconds: half }
        newSceneDuration = rest
      }
      const newScene: Scene = {
        index: 0,
        text: 'New scene',
        keywords: ['scene'],
        duration_seconds: newSceneDuration,
        image_mode: 'placeholder',
        image_path: undefined,
        image_url: undefined,
      }
      const nextRaw = [...prev.slice(0, idx), updatedCur, newScene, ...prev.slice(idx + 1)]
      return reindexScenes(nextRaw)
    })
    clearReplacementUploadState()
    clearScenePreviews()
  }

  /** Post-generation: duplicate scene (including image_path for shared uploads); reindex. */
  const duplicateSceneAfter = (sceneIndex: number) => {
    setEditedScenes(prev => {
      const idx = prev.findIndex(s => s.index === sceneIndex)
      if (idx < 0) return prev
      const source = prev[idx]
      const dup: Scene = {
        index: 0,
        text: source.text,
        keywords: [...source.keywords],
        duration_seconds: source.duration_seconds,
        image_url: source.image_url,
        image_mode: source.image_mode,
        image_path: source.image_path ?? undefined,
      }
      const nextRaw = [...prev.slice(0, idx + 1), dup, ...prev.slice(idx + 1)]
      return reindexScenes(nextRaw)
    })
    clearReplacementUploadState()
    clearScenePreviews()
  }

  /** Post-generation: remove scene if more than one remains; reindex. */
  const removeSceneFromEditor = (sceneIndex: number) => {
    setEditedScenes(prev => {
      if (prev.length <= 1) return prev
      return reindexScenes(prev.filter(s => s.index !== sceneIndex))
    })
    clearReplacementUploadState()
    clearScenePreviews()
  }

  const handleCopyScript = async () => {
    if (!result) return

    const textToCopy = editMode ? editedScript : result.script_text
    if (!textToCopy.trim()) return

    try {
      setCopying(true)
      setCopyLabel('Copy script')

      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(textToCopy)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = textToCopy
        textarea.style.position = 'fixed'
        textarea.style.left = '-9999px'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }

      setCopyLabel('Copied!')
      setTimeout(() => setCopyLabel('Copy script'), 2000)
    } catch (err) {
      console.error(err)
      setCopyLabel('Copy failed')
      setTimeout(() => setCopyLabel('Copy script'), 2000)
    } finally {
      setCopying(false)
    }
  }

  const fetchYoutubeStatus = async () => {
    try {
      setYoutubeChecking(true)
      const res = await fetch(`${API_BASE_URL}/auth/youtube/status`)
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Failed to fetch YouTube status')
      }
      const data: YouTubeAuthStatus = await res.json()
      setYoutubeConnected(data.connected)
    } catch (err) {
      console.error(err)
      setYoutubeConnected(false)
    } finally {
      setYoutubeChecking(false)
    }
  }

  const handleConnectYoutube = async () => {
    try {
      setYoutubeError(null)
      setYoutubeSuccessUrl(null)
      setYoutubeChecking(true)

      const res = await fetch(`${API_BASE_URL}/auth/youtube/start`)
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Failed to start YouTube authorization')
      }

      const data: YouTubeAuthStartResponse = await res.json()
      window.open(data.auth_url, '_blank', 'noopener,noreferrer')
    } catch (err: any) {
      console.error(err)
      setYoutubeError(err.message || 'Failed to start YouTube authorization')
    } finally {
      setYoutubeChecking(false)
    }
  }

  const handleUploadToYoutube = async () => {
    if (!result) return

    try {
      setYoutubeError(null)
      setYoutubeSuccessUrl(null)
      setYoutubeUploading(true)

      const res = await fetch(`${API_BASE_URL}/publish/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: result.video_path,
          title: youtubeTitle || topic,
          description: youtubeDescription || result.script_text,
          privacy_status: youtubePrivacy,
        }),
      })

      if (res.status === 401) {
        throw new Error('YouTube is not connected. Please connect your YouTube account first.')
      }

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Failed to upload video to YouTube')
      }

      const data: YouTubePublishResponse = await res.json()
      setYoutubeSuccessUrl(data.youtube_url)
    } catch (err: any) {
      console.error(err)
      setYoutubeError(err.message || 'Failed to upload video to YouTube')
    } finally {
      setYoutubeUploading(false)
    }
  }

  useEffect(() => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, themeMode)
    } catch {
      /* ignore */
    }
  }, [themeMode])

  useEffect(() => {
    const draft = loadProjectDraft()
    if (!draft) {
      draftHydratedRef.current = true
      return
    }
    setCreationMode(draft.creationMode)
    setTopic(draft.topic)
    setStyle(draft.style)
    setVideoType(draft.videoType)
    setDuration(draft.duration)
    setAspectRatio(draft.aspectRatio)
    setImageFitMode(draft.imageFitMode)
    if ((VISUAL_STYLE_OPTIONS as readonly string[]).includes(draft.visualStyle)) {
      setVisualStyle(draft.visualStyle as VisualStyle)
    }
    setEditedScript(draft.editedScript)
    setEditedScenes(draft.editedScenes)
    setManualImageModes(draft.manualImageModes)
    setManualNarrationSource(draft.manualNarrationSource)
    setPersistedManualNarration(draft.persistedManualNarration)
    setExistingSubtitles(draft.existingSubtitles)
    setExistingSourceVideoPath(draft.existingSourceVideoPath)
    setExistingSourceVideoUrl(draft.existingSourceVideoUrl)
    setBackgroundMusic(draft.backgroundMusic)
    setBackgroundMusicVolume(draft.backgroundMusicVolume)
    setMotionEffect(draft.motionEffect)
    setMotionIntensity(draft.motionIntensity)
    setSubtitleStyle(draft.subtitleStyle)
    setBrandingEnabled(draft.brandingEnabled)
    setBrandingLogoPath(draft.brandingLogoPath)
    setBrandingLogoUrl(draft.brandingLogoUrl)
    setBrandingPosition(draft.brandingPosition)
    setBrandingSize(draft.brandingSize)
    setBrandingOpacity(draft.brandingOpacity)
    setEditMode(draft.editMode)
    setProjectSavedAt(draft.savedAt)
    if (draft.latestResult && !draft.activeRenderJobId) {
      setResult(draft.latestResult as VideoResponse)
      setVideoVersion(v => v + 1)
    }
    if (draft.activeRenderJobId) {
      setActiveRenderJobId(draft.activeRenderJobId)
      void resumeRenderJobIfNeeded(draft.activeRenderJobId, false)
    }
    draftHydratedRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!draftHydratedRef.current || suppressAutosaveRef.current) return
    if (autosaveTimerRef.current !== undefined) {
      window.clearTimeout(autosaveTimerRef.current)
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      persistProjectDraft()
    }, 800)
    return () => {
      if (autosaveTimerRef.current !== undefined) {
        window.clearTimeout(autosaveTimerRef.current)
      }
    }
  }, [
    persistProjectDraft,
    creationMode,
    topic,
    style,
    videoType,
    duration,
    aspectRatio,
    imageFitMode,
    visualStyle,
    editedScript,
    editedScenes,
    manualImageModes,
    manualNarrationSource,
    persistedManualNarration,
    existingSubtitles,
    existingSourceVideoPath,
    existingSourceVideoUrl,
    backgroundMusic,
    backgroundMusicVolume,
    motionEffect,
    motionIntensity,
    subtitleStyle,
    brandingEnabled,
    brandingLogoPath,
    brandingLogoUrl,
    brandingPosition,
    brandingSize,
    brandingOpacity,
    activeRenderJobId,
    result,
    editMode,
  ])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible' || !activeRenderJobId) return
      void resumeRenderJobIfNeeded(activeRenderJobId, true)
    }
    const onFocus = () => {
      if (activeRenderJobId) void resumeRenderJobIfNeeded(activeRenderJobId, true)
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onFocus)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onFocus)
    }
  }, [activeRenderJobId, resumeRenderJobIfNeeded])

  useEffect(() => () => stopJobPolling(), [])

  useEffect(() => {
    fetchYoutubeStatus().catch(() => undefined)

    const allowedOrigins = ['http://localhost:8000', 'http://127.0.0.1:8000']

    const handleMessage = (event: MessageEvent) => {
      if (!allowedOrigins.includes(event.origin)) return

      const data = event.data as any
      if (data && data.source === 'sacredclips' && data.type === 'youtube-auth-complete') {
        fetchYoutubeStatus().catch(() => undefined)
      }
    }

    window.addEventListener('message', handleMessage)
    return () => {
      window.removeEventListener('message', handleMessage)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!loading || activeRenderJobId) return

    const stagePlanByProfile: Record<GenerationProfile, { threshold: number; label: string }[]> = {
      ai: [
        { threshold: 15, label: 'Preparing request' },
        { threshold: 35, label: 'Generating script' },
        { threshold: 65, label: 'Creating visuals' },
        { threshold: 80, label: 'Generating narration' },
        { threshold: 95, label: 'Rendering video' },
      ],
      regenerate: [
        { threshold: 15, label: 'Preparing request' },
        { threshold: 40, label: 'Creating visuals' },
        { threshold: 70, label: 'Generating narration' },
        { threshold: 95, label: 'Rendering video' },
      ],
      manual_tts: [
        { threshold: 15, label: 'Preparing request' },
        { threshold: 35, label: 'Processing uploads' },
        { threshold: 65, label: 'Creating/collecting visuals' },
        { threshold: 80, label: 'Generating narration' },
        { threshold: 95, label: 'Rendering video' },
      ],
      manual_upload: [
        { threshold: 20, label: 'Preparing request' },
        { threshold: 45, label: 'Processing uploads' },
        { threshold: 75, label: 'Creating/collecting visuals' },
        { threshold: 92, label: 'Rendering video' },
        { threshold: 95, label: 'Finalizing video' },
      ],
      subtitles: [
        { threshold: 25, label: 'Uploading video' },
        { threshold: 55, label: 'Preparing subtitles' },
        { threshold: 92, label: 'Burning subtitles' },
        { threshold: 95, label: 'Finalizing video' },
      ],
    }

    const stagePlan = stagePlanByProfile[generationProfile]

    const id = window.setInterval(() => {
      setGenerationProgress(prev => {
        if (prev >= 95) return prev
        const delta = prev < 25 ? 2 : prev < 60 ? 1.4 : prev < 85 ? 0.9 : 0.45
        const next = Math.min(95, prev + delta)
        const stage = stagePlan.find(step => next <= step.threshold)?.label ?? 'Rendering video'
        setGenerationStage(stage)
        return next
      })
    }, 650)

    return () => window.clearInterval(id)
  }, [loading, generationProfile, activeRenderJobId])

  useEffect(() => {
    const el = musicPreviewRef.current
    if (!el) return
    el.volume = Math.min(1, Math.max(0, backgroundMusicVolume))
  }, [backgroundMusicVolume, backgroundMusic])

  useEffect(() => {
    if (!uploadedVideoFile) {
      stopExistingSubtitlePreview()
      setUploadedVideoUrl('')
      setExistingVideoCurrentTime(0)
      return undefined
    }
    const url = URL.createObjectURL(uploadedVideoFile)
    setUploadedVideoUrl(url)
    setExistingVideoCurrentTime(0)
    return () => {
      stopExistingSubtitlePreview()
      URL.revokeObjectURL(url)
    }
  }, [uploadedVideoFile])

  useEffect(() => {
    const shouldPreview =
      creationMode === 'manual' && manualNarrationSource === 'upload' && manualAudioUpload != null

    if (!shouldPreview) {
      stopManualSceneAudioPreview()
      setUploadedAudioUrl('')
      setUploadedAudioDuration(0)
      setUploadedAudioCurrentTime(0)
      setSceneCutTimes([])
      clearScenePreviews()
      return undefined
    }

    const url = URL.createObjectURL(manualAudioUpload)
    setUploadedAudioUrl(url)
    setSceneCutTimes([])
    setUploadedAudioDuration(0)
    setUploadedAudioCurrentTime(0)
    clearScenePreviews()

    return () => {
      stopManualSceneAudioPreview()
      URL.revokeObjectURL(url)
    }
  }, [creationMode, manualNarrationSource, manualAudioUpload])

  useEffect(() => {
    if (activeAudioSceneIndex == null) return
    if (!editedScenes.some(s => s.index === activeAudioSceneIndex)) {
      stopManualSceneAudioPreview()
      return
    }
    const sorted = [...editedScenes].sort((a, b) => a.index - b.index)
    let t = 0
    let r: { start: number; end: number } | null = null
    for (const s of sorted) {
      const dur = Number.isFinite(s.duration_seconds) ? Math.max(0, s.duration_seconds) : 0
      if (s.index === activeAudioSceneIndex) {
        r = { start: t, end: t + dur }
        break
      }
      t += dur
    }
    if (!r) {
      stopManualSceneAudioPreview()
      return
    }
    sceneSegmentEndRef.current = r.end
    const el = sceneAudioPreviewRef.current
    if (el && !el.paused && el.currentTime >= r.end - 0.05) {
      stopManualSceneAudioPreview()
    }
  }, [editedScenes, activeAudioSceneIndex])

  const syncAudioDurationFromElement = () => {
    const el = audioRef.current
    if (!el) return
    const d = el.duration
    if (Number.isFinite(d) && d > 0 && d !== Number.POSITIVE_INFINITY) {
      setUploadedAudioDuration(d)
    }
  }

  const syncAudioCurrentTimeFromElement = () => {
    const el = audioRef.current
    if (!el) return
    const t = el.currentTime
    if (Number.isFinite(t)) setUploadedAudioCurrentTime(t)
  }

  const addSceneCutAtPlayhead = () => {
    const el = audioRef.current
    if (!el) return
    const dur = el.duration
    if (!Number.isFinite(dur) || dur <= 0 || dur === Number.POSITIVE_INFINITY) return
    const t = el.currentTime
    if (t <= 0 || t >= dur) return
    setSceneCutTimes(prev => {
      if (prev.some(c => Math.abs(c - t) < SCENE_CUT_MIN_SEPARATION_SEC)) return prev
      return [...prev, t].sort((a, b) => a - b)
    })
  }

  const removeSceneCutAtIndex = (index: number) => {
    setSceneCutTimes(prev => prev.filter((_, i) => i !== index))
  }

  const applySceneCutsToScenes = () => {
    stopManualSceneAudioPreview()
    clearScenePreviews()
    const el = audioRef.current
    const fromEl = el?.duration
    const total =
      Number.isFinite(fromEl) && fromEl! > 0 && fromEl !== Number.POSITIVE_INFINITY
        ? fromEl!
        : uploadedAudioDuration
    const segs = computeSegmentDurationsFromCuts(sceneCutTimes, total)
    if (!segs) {
      setError(
        'Cannot apply cuts: wait for the audio duration to load, and ensure each cut is after 0 and before the end of the file.',
      )
      return
    }
    setError(null)
    const prevScenes = editedScenes
    const nextUploads: Record<number, File | undefined> = {}
    const nextModes: Record<number, ManualImageMode> = {}
    const newScenes: Scene[] = segs.map((dur, i) => {
      const roundedDur = roundToHalfSecond(dur)
      const newIndex = i + 1
      const old = prevScenes.find(s => s.index === newIndex)
      if (old) {
        if (manualUploads[newIndex]) nextUploads[newIndex] = manualUploads[newIndex]
        if (manualImageModes[newIndex]) nextModes[newIndex] = manualImageModes[newIndex]
        return {
          ...old,
          index: newIndex,
          text: old.text?.trim() ? old.text : `Manual visual scene ${newIndex}`,
          keywords: old.keywords?.length ? [...old.keywords] : ['manual scene'],
          duration_seconds: roundedDur,
        }
      }
      return {
        index: newIndex,
        text: `Manual visual scene ${newIndex}`,
        keywords: ['manual scene'],
        duration_seconds: roundedDur,
        image_url: null,
      }
    })
    setEditedScenes(newScenes)
    setManualUploads(nextUploads)
    setManualImageModes(nextModes)
  }

  return (
    <div className="app-shell" data-theme={themeMode}>
      <div className="app-container">
        <header className="app-header">
          <div className="app-header-brand">
            <div className="badge">Religious video generator</div>
            <div className="title">
              <span className="title-accent" />
              SacredClips
            </div>
            <p className="subtitle">
              Turn a religious or spiritual topic into a short educational explainer video.
            </p>
          </div>
          <div className="app-header-actions">
            <div className="theme-toggle" role="group" aria-label="Theme">
              <button
                type="button"
                className={`theme-toggle-btn${themeMode === 'light' ? ' is-active' : ''}`}
                onClick={() => setThemeMode('light')}
                aria-pressed={themeMode === 'light'}
              >
                Light
              </button>
              <button
                type="button"
                className={`theme-toggle-btn${themeMode === 'dark' ? ' is-active' : ''}`}
                onClick={() => setThemeMode('dark')}
                aria-pressed={themeMode === 'dark'}
              >
                Dark
              </button>
            </div>
            <div className="header-status-chip">
              <span className="status-dot" />
              {loading ? 'Generating' : result ? 'Ready' : 'Idle'} · Backend
            </div>
            {projectSavedAt ? (
              <span className="project-save-status" title={`Saved ${projectSavedAt}`}>
                Project saved locally
              </span>
            ) : null}
            <button type="button" className="button button-secondary button-compact" onClick={handleClearSavedProject}>
              Clear saved project
            </button>
            {result ? (
              <button type="button" className="button button-secondary" onClick={resetToNewVideo}>
                Start new video
              </button>
            ) : null}
          </div>
        </header>

        {renderReconnectNotice ? (
          <div className="reconnect-notice" role="status">
            {renderReconnectNotice}
          </div>
        ) : null}

        {projectResetNotice ? (
          <div className="reconnect-notice project-reset-notice" role="status">
            {projectResetNotice}
          </div>
        ) : null}

        {(loading || error) && (
          <div className="global-status-bar" aria-live="polite">
            {loading && (
              <section className="status-panel">
                <div className="generation-progress-label">
                  {generationStage || 'Generating your video...'}
                </div>
                <div className="generation-progress-meta">
                  {activeRenderJobId ? 'Progress' : 'Estimated progress'}: {Math.floor(generationProgress)}%
                </div>
                <div className="generation-progress-bar">
                  <div
                    className="generation-progress-fill"
                    style={{ width: `${Math.max(5, Math.floor(generationProgress))}%` }}
                  />
                </div>
                <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                  Final rendering may take longer for longer videos.
                </p>
              </section>
            )}
            {error ? <section className="status-panel"><div className="error">{error}</div></section> : null}
          </div>
        )}

        <form className="dashboard-layout" onSubmit={handleFormSubmit}>
          <aside className="sidebar-rail">
            <div className="sidebar-rail-scroll">
            <StaticCard title="Project setup" subtitle="Mode, topic, and core inputs">
            <div>
              <div className="field-label">Creation mode</div>
              <div className="range-row">
                <label className="radio-label">
                  <input
                    type="radio"
                    name="creation-mode"
                    checked={creationMode === 'ai'}
                    onChange={() => handleCreationModeChange('ai')}
                  />
                  AI mode
                </label>
                <label className="radio-label">
                  <input
                    type="radio"
                    name="creation-mode"
                    checked={creationMode === 'manual'}
                    onChange={() => handleCreationModeChange('manual')}
                  />
                  Manual mode
                </label>
                <label className="radio-label">
                  <input
                    type="radio"
                    name="creation-mode"
                    checked={creationMode === 'existing'}
                    onChange={() => handleCreationModeChange('existing')}
                  />
                  Existing video + subtitles
                </label>
              </div>
              <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                AI generates a new clip. Manual mode builds from your script/uploads. Existing video mode only burns
                subtitles onto a video you provide.
              </p>
            </div>

            <div>
              <div className="field-label">Topic (religious / spiritual)</div>
              <input
                className="input"
                value={topic}
                onChange={e => setTopic(e.target.value)}
                placeholder="e.g. What is the Eucharist?"
                required
              />
            </div>

            {creationMode === 'ai' && (
              <div>
                <div className="field-label">Narration style</div>
                <textarea
                  className="textarea"
                  value={style}
                  onChange={e => setStyle(e.target.value)}
                />
              </div>
            )}

            {creationMode === 'manual' && !result && (
              <div>
                <div className="field-label">Script (narration to read aloud)</div>
                <textarea
                  className="textarea textarea-script-edit"
                  value={editedScript}
                  onChange={e => setEditedScript(e.target.value)}
                  placeholder="Paste your full narration here..."
                  rows={8}
                  required={creationMode === 'manual' && manualNarrationSource === 'tts'}
                />
                <div className="button-row" style={{ marginTop: '0.5rem' }}>
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={loading}
                    onClick={() => {
                      const next = splitScriptIntoScenes(editedScript, duration)
                      if (!next.length) {
                        setError('Nothing to split — paste some text first.')
                        return
                      }
                      setError(null)
                      setEditedScenes(next)
                    }}
                  >
                    Split script into scenes
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={loading}
                    onClick={addManualScene}
                  >
                    Add scene
                  </button>
                </div>
                <div className="field-label" style={{ marginTop: '0.75rem' }}>
                  Narration source
                </div>
                <div className="range-row">
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="manual-narration-source"
                      checked={manualNarrationSource === 'tts'}
                      onChange={() => {
                        setManualNarrationSource('tts')
                        setPersistedManualNarration(null)
                      }}
                    />
                    Generate AI voice from script
                  </label>
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="manual-narration-source"
                      checked={manualNarrationSource === 'upload'}
                      onChange={() => setManualNarrationSource('upload')}
                    />
                    Upload my own audio
                  </label>
                </div>
                {manualNarrationSource === 'upload' && (
                  <div style={{ marginTop: '0.5rem' }}>
                    <div className="field-label">Narration audio file</div>
                    <input
                      type="file"
                      accept="audio/*"
                      onChange={e => setManualAudioUpload(e.target.files?.[0])}
                    />
                    <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                      Uploaded narration will be used as the video audio track. Use the timing assistant in the
                      workspace to split scenes.
                    </p>
                  </div>
                )}
              </div>
            )}

            {creationMode !== 'existing' && (
              <div>
                <div className="field-label">
                  Desired video length ({durationMin}s–{durationMax}s)
                </div>
                <div className="range-row">
                  <div className="range-input">
                    <input
                      type="range"
                      min={durationMin}
                      max={durationMax}
                      step={durationStep}
                      value={duration}
                      onChange={e => setDuration(Number(e.target.value))}
                      style={{ width: '100%' }}
                    />
                  </div>
                  <div className="range-value">{duration}s</div>
                </div>
              </div>
            )}
            </StaticCard>

            {creationMode !== 'existing' && (
            <CollapsibleCard title="Visual settings" subtitle="Style, format, and image fit" defaultOpen>
              <div>
                <div className="field-label">Visual style {creationMode === 'ai' ? '(AI images)' : '(placeholders)'}</div>
                <select
                  className="select input-full"
                  value={visualStyle}
                  onChange={e => setVisualStyle(e.target.value as VisualStyle)}
                >
                  {VISUAL_STYLE_OPTIONS.map(opt => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="field-label">Content format</div>
                <select
                  className="select input-full"
                  value={videoType}
                  onChange={e => handleVideoTypeChange(e.target.value as VideoType)}
                >
                  <option value="normal">Normal YouTube video (16:9 horizontal)</option>
                  <option value="shorts">Shorts / TikTok / Reels (9:16 vertical)</option>
                </select>
                <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                  {videoType === 'normal' ? 'Output format: 16:9 horizontal' : 'Output format: 9:16 vertical'}
                </p>
              </div>
              <div>
                <div className="field-label">Image fit</div>
                <select
                  className="select input-full"
                  value={imageFitMode}
                  onChange={e => setImageFitMode(e.target.value as ImageFitMode)}
                >
                  <option value="fit">Fit full image</option>
                  <option value="fill">Fill screen / crop</option>
                </select>
                <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                  Fit keeps the whole image visible; fill crops to cover the frame.
                </p>
              </div>
            </CollapsibleCard>
            )}

            {creationMode !== 'existing' && (
            <CollapsibleCard title="Audio & music" subtitle="Optional background track" defaultOpen={false}>
              <div>
                <div className="field-label">Background music</div>
                <select
                  className="select input-full"
                  value={backgroundMusic}
                  onChange={e => setBackgroundMusic(e.target.value as BackgroundMusic)}
                >
                  <option value="none">None</option>
                  <option value="peaceful_piano">Peaceful piano</option>
                  <option value="ambient_pad">Ambient pad</option>
                  <option value="soft_strings">Soft strings</option>
                  <option value="gentle_choir">Gentle choir</option>
                </select>
                {backgroundMusic !== 'none' && (
                  <>
                    <div className="field-label" style={{ marginTop: '0.75rem' }}>
                      Music volume ({Math.round(backgroundMusicVolume * 100)}%)
                    </div>
                    <div className="range-row">
                      <div className="range-input">
                        <input
                          type="range"
                          min={0.02}
                          max={0.3}
                          step={0.01}
                          value={backgroundMusicVolume}
                          onChange={e => setBackgroundMusicVolume(Number(e.target.value))}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>
                    <audio
                      ref={musicPreviewRef}
                      key={backgroundMusic}
                      className="music-preview-audio"
                      controls
                      src={backgroundMusicPreviewUrl(backgroundMusic) ?? undefined}
                    />
                    <p className="footer-hint">Keep volume low so narration remains clear.</p>
                  </>
                )}
              </div>
            </CollapsibleCard>
            )}

            {creationMode !== 'existing' && (
            <CollapsibleCard title="Motion" subtitle="Image movement effects" defaultOpen={false}>
              <div>
                <div className="field-label">Motion effect</div>
                <select
                  className="select input-full"
                  value={motionEffect}
                  onChange={e => setMotionEffect(e.target.value as MotionEffect)}
                >
                  <option value="none">None</option>
                  <option value="gentle_zoom">Gentle zoom</option>
                  <option value="slow_pan">Slow pan</option>
                  <option value="ken_burns">Ken Burns</option>
                </select>
              </div>
              <div style={{ opacity: motionEffect === 'none' ? 0.55 : 1 }}>
                <div className="field-label">Motion intensity</div>
                <select
                  className="select input-full"
                  value={motionIntensity}
                  disabled={motionEffect === 'none'}
                  onChange={e => setMotionIntensity(e.target.value as MotionIntensity)}
                >
                  <option value="subtle">Subtle</option>
                  <option value="medium">Medium</option>
                  <option value="strong">Strong</option>
                </select>
              </div>
            </CollapsibleCard>
            )}

            <CollapsibleCard title="Captions" subtitle="Subtitle style" defaultOpen>
              <div>
                <div className="field-label">Subtitles</div>
                <select
                  className="select input-full"
                  value={subtitleStyle}
                  onChange={e => {
                    setSubtitleStyle(e.target.value as SubtitleStyle)
                    clearExistingVideoResult()
                  }}
                >
                  <option value="off">Off</option>
                  <option value="minimal">Minimal</option>
                  <option value="cinematic">Cinematic</option>
                  <option value="shorts">Shorts style</option>
                </select>
                <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                  {creationMode === 'existing'
                    ? 'Manual subtitle segments use the exact start and end times you enter.'
                    : 'Subtitles are split into readable chunks during each scene.'}
                </p>
              </div>
            </CollapsibleCard>

            <CollapsibleCard title="Branding" subtitle="Logo watermark" defaultOpen={false}>
              <div className="branding-section">
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={brandingEnabled}
                    onChange={e => setBrandingEnabled(e.target.checked)}
                  />
                  <span>Enable logo watermark</span>
                </label>
                {brandingEnabled && (
                  <>
                    <div className="branding-upload-row">
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        onChange={handleBrandingLogoSelect}
                        disabled={brandingUploading}
                      />
                      {brandingLogoPath && (
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={clearBrandingLogo}
                        >
                          Remove logo
                        </button>
                      )}
                    </div>
                    {brandingUploading && <p className="footer-hint">Uploading logo…</p>}
                    {brandingLogoDisplayUrl && (
                      <div className="branding-logo-preview-wrap">
                        <img
                          src={brandingLogoDisplayUrl}
                          alt="Logo preview"
                          className="branding-logo-preview"
                        />
                      </div>
                    )}
                    <div className="field-label" style={{ marginTop: '0.5rem' }}>Position</div>
                    <select
                      className="select input-full"
                      value={brandingPosition}
                      onChange={e => setBrandingPosition(e.target.value as BrandingPosition)}
                    >
                      <option value="top_left">Top left</option>
                      <option value="top_right">Top right</option>
                      <option value="bottom_left">Bottom left</option>
                      <option value="bottom_right">Bottom right</option>
                    </select>
                    <div className="field-label" style={{ marginTop: '0.5rem' }}>Size</div>
                    <select
                      className="select input-full"
                      value={brandingSize}
                      onChange={e => setBrandingSize(e.target.value as BrandingSize)}
                    >
                      <option value="small">Small</option>
                      <option value="medium">Medium</option>
                      <option value="large">Large</option>
                    </select>
                    <div className="field-label" style={{ marginTop: '0.5rem' }}>
                      Opacity ({Math.round(brandingOpacity * 100)}%)
                    </div>
                    <div className="range-row">
                      <div className="range-input">
                        <input
                          type="range"
                          min={0.1}
                          max={1}
                          step={0.05}
                          value={brandingOpacity}
                          onChange={e => setBrandingOpacity(Number(e.target.value))}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>
                  </>
                )}
              </div>
            </CollapsibleCard>

            <CollapsibleCard title="YouTube" subtitle="Connection status" defaultOpen={false}>
              <p className="youtube-sidebar-summary">
                {youtubeChecking
                  ? 'Checking YouTube status…'
                  : youtubeConnected
                    ? 'Connected — open the publishing panel in the workspace after rendering.'
                    : 'Not connected — connect from the publishing panel after rendering.'}
              </p>
              <button
                type="button"
                className="button button-secondary"
                onClick={handleConnectYoutube}
                disabled={youtubeChecking}
              >
                {youtubeConnected ? 'Reconnect YouTube' : 'Connect YouTube'}
              </button>
            </CollapsibleCard>
            </div>

            <div className="sidebar-submit-bar">
              <button className="button" type="submit" disabled={loading}>
                <span className="button-icon">{loading ? '⏳' : '✨'}</span>
                {loading
                  ? creationMode === 'ai'
                    ? 'Generating sacred clip…'
                    : creationMode === 'existing'
                      ? 'Rendering subtitles…'
                      : 'Building manual clip…'
                  : creationMode === 'ai'
                    ? 'Generate video'
                    : creationMode === 'existing'
                      ? existingSourceVideoPath
                        ? 'Re-render subtitles'
                        : 'Render subtitled video'
                      : 'Create manual video'}
              </button>
            </div>
          </aside>

          <main className="workspace-main">
            {!result && !loading && (
              <section className="workspace-panel idle-tips-panel">
                <div className="pill-row">
                  <div className="pill">What is baptism in Christianity?</div>
                  <div className="pill">Basics of baptism</div>
                  <div className="pill">What is the Trinity?</div>
                  <div className="pill">What is a Sabbath?</div>
                </div>
                <p className="footer-hint" style={{ marginTop: '0.5rem' }}>
                  Tip: ask for short explainers of holidays, practices, symbols, or concepts.
                </p>
              </section>
            )}

            {creationMode === 'manual' && manualNarrationSource === 'upload' && manualAudioUpload && !result && (
              <CollapsibleCard title="Timing assistant" subtitle="Split uploaded narration into scenes" defaultOpen={false}>
                <p className="footer-hint">
                  Play your narration and click &quot;Add scene cut here&quot; when the image should change.
                </p>
                <div className="result-block result-block--expanded">
                  {uploadedAudioUrl ? (
                    <>
                      <audio
                        key={uploadedAudioUrl}
                        ref={audioRef}
                        src={uploadedAudioUrl}
                        controls
                        onPlay={stopManualSceneAudioPreview}
                        onLoadedMetadata={syncAudioDurationFromElement}
                        onDurationChange={syncAudioDurationFromElement}
                        onTimeUpdate={syncAudioCurrentTimeFromElement}
                        onSeeking={syncAudioCurrentTimeFromElement}
                        onSeeked={syncAudioCurrentTimeFromElement}
                        className="timing-assistant-audio"
                      />
                      {editedScenes.length > 0 && (
                        <audio
                          ref={sceneAudioPreviewRef}
                          key={`scene-seg-${uploadedAudioUrl}`}
                          src={uploadedAudioUrl}
                          preload="auto"
                          className="scene-audio-preview-hidden"
                          onTimeUpdate={onScenePreviewAudioTimeUpdate}
                        />
                      )}
                    </>
                  ) : (
                    <p className="footer-hint">Preparing audio preview…</p>
                  )}
                  <div className="action-row">
                    <span className="footer-hint" style={{ marginTop: 0 }}>
                      Current: {formatAudioSeconds(uploadedAudioCurrentTime)}
                    </span>
                    <span className="footer-hint" style={{ marginTop: 0 }}>
                      Duration: {formatAudioSeconds(uploadedAudioDuration)}
                    </span>
                  </div>
                  <div className="action-row">
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={loading || !uploadedAudioUrl}
                      onClick={addSceneCutAtPlayhead}
                    >
                      Add scene cut here
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={
                        loading ||
                        !uploadedAudioUrl ||
                        !Number.isFinite(uploadedAudioDuration) ||
                        uploadedAudioDuration <= 0
                      }
                      onClick={applySceneCutsToScenes}
                    >
                      Apply cuts to scenes
                    </button>
                  </div>
                  {sceneCutTimes.length > 0 && (
                    <div style={{ marginTop: '0.5rem' }}>
                      <div className="field-label">Scene cuts ({sceneCutTimes.length})</div>
                      <ul className="scene-cut-list">
                        {sceneCutTimes.map((t, i) => (
                          <li key={`${i}-${t}`} className="scene-cut-list-item">
                            <span className="footer-hint" style={{ marginTop: 0 }}>
                              Cut {i + 1}: {t.toFixed(3)}s
                            </span>
                            <button
                              type="button"
                              className="tiny-button"
                              disabled={loading}
                              onClick={() => removeSceneCutAtIndex(i)}
                            >
                              Remove
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </CollapsibleCard>
            )}

            {creationMode === 'existing' && (
              <section className="workspace-panel">
                <div className="workspace-panel-header">
                  <h2 className="workspace-panel-title">Existing video editor</h2>
                </div>
                <div>
                  <div className="field-label">Existing video</div>
                  <input
                    type="file"
                    accept=".mp4,.mov,.mkv,.webm,video/mp4,video/quicktime,video/x-matroska,video/webm"
                    onChange={e => handleExistingVideoFileChange(e.target.files?.[0])}
                  />
                  <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                    Upload MP4, MOV, MKV, or WebM. SacredClips burns subtitles onto your video.
                  </p>
                  {existingSourceVideoPath && !uploadedVideoFile ? (
                    <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                      Reusing source from previous render — no re-upload needed.
                    </p>
                  ) : null}
                </div>

                {existingVideoPreviewSrc ? (
                  <div style={{ marginTop: '0.85rem' }}>
                    <div className="field-label">Subtitle style preview</div>
                    <div className="existing-video-preview">
                      <video
                        ref={existingVideoPreviewRef}
                        controls
                        src={existingVideoPreviewSrc}
                        onTimeUpdate={e => syncExistingVideoPreviewTime(e.currentTarget)}
                        onSeeked={e => syncExistingVideoPreviewTime(e.currentTarget)}
                        onLoadedMetadata={e => {
                          syncExistingVideoPreviewTime(e.currentTarget)
                          syncExistingVideoLayout(e.currentTarget)
                        }}
                        onPause={() => {
                          if (activeExistingSubtitlePreviewId) {
                            existingSubtitlePreviewEndRef.current = null
                            setActiveExistingSubtitlePreviewId(null)
                          }
                        }}
                      />
                      {activeExistingSubtitle && isExistingSubtitleStyle(subtitleStyle) && (
                          <ExistingVideoSubtitleOverlay
                            text={activeExistingSubtitle.text}
                            style={subtitleStyle}
                            layout={existingVideoLayout}
                          />
                        )}
                    </div>
                  </div>
                ) : null}

                <div style={{ marginTop: '1rem' }}>
                  <div className="section-header-row">
                    <div className="field-label">Subtitle segments</div>
                    <button type="button" className="tiny-button" onClick={addExistingSubtitle}>
                      + Add subtitle
                    </button>
                  </div>
                  <div className="subtitle-segment-timeline" style={{ marginTop: '0.5rem' }}>
                    <div className="subtitle-segment-track">
                    {existingSubtitles.map((item, idx) => (
                      <div key={item.id} className="subtitle-segment-card">
                        <div className="scene-card-header">
                          <div className="scene-title">Subtitle {idx + 1}</div>
                          <div className="scene-card-actions">
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => toggleExistingSubtitlePreview(item)}
                              disabled={!existingVideoPreviewSrc || loading}
                            >
                              {activeExistingSubtitlePreviewId === item.id ? 'Stop preview' : 'Preview segment'}
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => duplicateExistingSubtitle(item.id)}
                            >
                              Duplicate
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => removeExistingSubtitle(item.id)}
                              disabled={existingSubtitles.length <= 1}
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                        <div className="subtitle-time-grid">
                          <label>
                            <span className="field-label">Start</span>
                            <input
                              className="input"
                              type="number"
                              min={0}
                              step={0.1}
                              value={item.start_seconds}
                              onChange={e =>
                                updateExistingSubtitle(item.id, {
                                  start_seconds: Number.parseFloat(e.target.value.replace(',', '.')) || 0,
                                })
                              }
                            />
                          </label>
                          <label>
                            <span className="field-label">End</span>
                            <input
                              className="input"
                              type="number"
                              min={0}
                              step={0.1}
                              value={item.end_seconds}
                              onChange={e =>
                                updateExistingSubtitle(item.id, {
                                  end_seconds: Number.parseFloat(e.target.value.replace(',', '.')) || 0,
                                })
                              }
                            />
                          </label>
                        </div>
                        <div className="field-label">Text</div>
                        <textarea
                          className="textarea"
                          rows={3}
                          value={item.text}
                          onChange={e => updateExistingSubtitle(item.id, { text: e.target.value })}
                        />
                        {subtitleStyle !== 'off' && (() => {
                          const charCount = item.text.trim().length
                          const maxRec = getRecommendedSubtitleMaxChars(subtitleStyle, existingVideoPortrait)
                          const fit =
                            charCount > 0 && isExistingSubtitleStyle(subtitleStyle)
                              ? wrapSubtitlePreviewLines(item.text, subtitleStyle, existingVideoLayout)
                              : null
                          const tooLong = charCount > maxRec || Boolean(fit?.truncated)
                          return (
                            <>
                              <p className="footer-hint subtitle-char-guidance">
                                {charCount} characters · recommended max ~{maxRec}
                              </p>
                              {tooLong ? (
                                <p className="footer-hint footer-hint--warning">
                                  This may be too long for one subtitle. Consider splitting it into another
                                  segment.
                                </p>
                              ) : null}
                            </>
                          )
                        })()}
                      </div>
                    ))}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {editedScenes.length > 0 && creationMode === 'manual' && !result && (
              <section className="workspace-panel">
                <div className="workspace-panel-header">
                  <h2 className="workspace-panel-title">Scene timeline (before render)</h2>
                </div>
                <div className="scene-timeline">
                  <div className="scene-timeline-track">
                    {editedScenes.map(scene => (
                      <div key={scene.index} className="scene-card">
                        <div className="scene-card-header">
                          <div className="scene-title">Scene {scene.index}</div>
                          <div className="scene-card-actions">
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => duplicateManualScene(scene.index)}
                            >
                              Duplicate
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => removeManualScene(scene.index)}
                              disabled={editedScenes.length <= 1}
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                        <textarea
                          className="textarea"
                          rows={4}
                          value={scene.text}
                          onChange={e => updateScene(scene.index, { text: e.target.value })}
                        />
                        <div className="field-label" style={{ marginTop: '0.15rem' }}>
                          Image guidance keywords
                        </div>
                        <p className="footer-hint" style={{ marginTop: '0.2rem', marginBottom: '0.2rem' }}>
                          Used only if you choose Generate AI image for this scene.
                        </p>
                        <input
                          className="input"
                          value={scene.keywords.join(', ')}
                          onChange={e => {
                            const kws = e.target.value
                              .split(',')
                              .map(s => s.trim())
                              .filter(Boolean)
                            updateScene(scene.index, {
                              keywords: kws.length ? kws : ['manual scene'],
                            })
                          }}
                        />
                        <div className="field-label" style={{ marginTop: '0.35rem' }}>
                          Duration (seconds)
                        </div>
                        <input
                          className="input"
                          type="number"
                          min={1}
                          step={0.5}
                          value={scene.duration_seconds}
                          onChange={e =>
                            updateScene(scene.index, {
                            duration_seconds: roundToHalfSecond(
                              Number.parseFloat(e.target.value.replace(',', '.')) || 5,
                            ),
                            })
                          }
                        />
                        {creationMode === 'manual' &&
                          manualNarrationSource === 'upload' &&
                          manualAudioUpload &&
                          !result &&
                          editedScenes.length > 0 &&
                          manualSceneAudioRangesByIndex[scene.index] != null && (
                            <div style={{ marginTop: '0.45rem' }}>
                              <p className="footer-hint" style={{ marginTop: 0, marginBottom: '0.3rem' }}>
                                Scene audio:{' '}
                                {formatAudioMmSs(manualSceneAudioRangesByIndex[scene.index]!.start)} →{' '}
                                {formatAudioMmSs(manualSceneAudioRangesByIndex[scene.index]!.end)}
                              </p>
                              <button
                                type="button"
                                className="tiny-button"
                                disabled={!uploadedAudioUrl || loading}
                                onClick={() => toggleManualSceneAudioPreview(scene.index)}
                              >
                                {activeAudioSceneIndex === scene.index && sceneAudioPreviewPlaying
                                  ? 'Stop audio'
                                  : 'Play scene audio'}
                              </button>
                            </div>
                          )}
                        <div className="field-label" style={{ marginTop: '0.35rem' }}>
                          Image source
                        </div>
                        <select
                          className="select input-full"
                          value={manualImageModes[scene.index] ?? (manualUploads[scene.index] ? 'upload' : 'placeholder')}
                          onChange={e => {
                            const nextMode = e.target.value as ManualImageMode
                            setManualImageModes(prev => ({
                              ...prev,
                              [scene.index]: nextMode,
                            }))
                            clearScenePreviews()
                          }}
                        >
                          <option value="upload">Upload image</option>
                          <option value="generate">Generate AI image</option>
                          <option value="placeholder">Placeholder only</option>
                        </select>
                        {(manualImageModes[scene.index] ?? (manualUploads[scene.index] ? 'upload' : 'placeholder')) === 'upload' && (
                          <>
                            <div className="field-label" style={{ marginTop: '0.35rem' }}>
                              Upload image
                            </div>
                            <input
                              type="file"
                              accept="image/*"
                              onChange={e => {
                                const f = e.target.files?.[0]
                                updateManualUploadForScene(scene.index, f)
                              }}
                            />
                          </>
                        )}
                        {(manualImageModes[scene.index] ?? (manualUploads[scene.index] ? 'upload' : 'placeholder')) === 'generate' && (
                          <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                            AI will generate this scene image using scene text + image guidance keywords.
                          </p>
                        )}
                        {(manualImageModes[scene.index] ?? (manualUploads[scene.index] ? 'upload' : 'placeholder')) === 'placeholder' && (
                          <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                            Placeholder will be used for this scene.
                          </p>
                        )}
                        {manualUploads[scene.index] ? (
                          <div className="scene-preview">
                            <img
                              alt={`Scene ${scene.index} preview`}
                              src={URL.createObjectURL(manualUploads[scene.index]!)}
                            />
                          </div>
                        ) : null}
                        <div style={{ marginTop: '0.5rem' }}>
                          <button
                            type="button"
                            className="tiny-button"
                            onClick={() => void handlePreviewScene(scene.index)}
                            disabled={loading || scenePreviewLoadingIndex === scene.index}
                          >
                            {scenePreviewLoadingIndex === scene.index ? 'Rendering preview…' : 'Preview scene'}
                          </button>
                          {scenePreviewUrlByIndex[scene.index] ? (
                            <div style={{ marginTop: '0.45rem' }}>
                              <div className="field-label">Scene preview</div>
                              <video
                                key={`manual-scpv-${scene.index}-${scenePreviewNonce}`}
                                controls
                                className="scene-preview-video"
                                src={`${API_BASE_URL}${scenePreviewUrlByIndex[scene.index]}?pv=${scenePreviewNonce}`}
                              />
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

          {result && (
            <>
              <section className="workspace-panel preview-card">
                <div
                  className={`alert ${
                    result.used_ai ? 'alert-success' : 'alert-warning'
                  }`}
                  style={{ marginBottom: '0.85rem' }}
                >
                  {creationMode === 'existing' ? (
                    <>
                      <strong>Existing video:</strong> Subtitles were burned onto your uploaded video. Original source
                      visuals were preserved.
                    </>
                  ) : result.used_ai ? (
                    <>
                      <strong>AI mode:</strong> This clip uses AI-generated script, images, and narration.
                    </>
                  ) : creationMode === 'manual' ? (
                    <>
                      <strong>Manual mode:</strong> This clip was created from your manual inputs. Some visuals may be
                      uploaded images, AI-generated images, or placeholders depending on your scene settings.
                    </>
                  ) : (
                    <>
                      <strong>Fallback/manual mode:</strong> AI generation was unavailable, so the app used fallback
                      content or your edited inputs.
                    </>
                  )}
                </div>
                <div className="workspace-panel-header">
                  <h2 className="workspace-panel-title">Video preview</h2>
                </div>
                <div className={`video-wrapper${videoType === 'shorts' || aspectRatio === '9:16' ? ' video-wrapper--vertical' : ''}`}>
                  <video
                    key={videoVersion}
                    controls
                    src={`${API_BASE_URL}${result.video_url}?v=${videoVersion}`}
                  />
                </div>
                <div className="action-row">
                  <a
                    className="button button-secondary"
                    href={`${API_BASE_URL}${result.video_url}?v=${videoVersion}`}
                    download
                  >
                    <span className="button-icon">⬇️</span>
                    Download MP4
                  </a>
                  <button type="button" className="button button-secondary" onClick={resetToNewVideo}>
                    Start new video
                  </button>
                </div>
                <p className="footer-hint">
                  Served from <code>{result.video_url}</code> — download and upload to your platform.
                </p>
              </section>

              {creationMode !== 'existing' && (
              <section className="workspace-panel">
                <div className="section-header-row">
                  <h2 className="workspace-panel-title">Script</h2>
                  <div className="action-row">
                    <button
                      type="button"
                      className="tiny-button"
                      onClick={handleCopyScript}
                      disabled={loading || copying}
                    >
                      {copyLabel}
                    </button>
                    <button
                      type="button"
                      className="tiny-button"
                      onClick={() => {
                        setEditMode(prev => !prev)
                        setEditedScript(result.script_text)
                      }}
                      disabled={loading}
                    >
                      {editMode ? 'Close editor' : 'Edit script'}
                    </button>
                  </div>
                </div>

                {editMode ? (
                  <div className="result-block result-block--expanded">
                    <textarea
                      className="textarea textarea-script-edit"
                      value={editedScript}
                      onChange={e => setEditedScript(e.target.value)}
                    />
                    <button
                      type="button"
                      className="button button-secondary full-width"
                      onClick={handleRebuildFromScenes}
                      disabled={loading || !result}
                    >
                      <span className="button-icon">🎬</span>
                      {loading ? 'Regenerating…' : 'Regenerate video (edited script + scenes)'}
                    </button>
                  </div>
                ) : (
                  <div className="script-preview-block">{result.script_text}</div>
                )}
              </section>
              )}

              {creationMode !== 'existing' && (
              <section className="workspace-panel">
                <div className="workspace-panel-header">
                  <h2 className="workspace-panel-title">Scene editor</h2>
                </div>
                <p className="footer-hint" style={{ marginBottom: '0.35rem' }}>
                  Total timeline duration: {totalSceneDuration.toFixed(1)}s · Target: {duration.toFixed(1)}s
                </p>
                {hasDurationWarning && (
                  <p className="footer-hint footer-hint--warning" style={{ marginBottom: '0.6rem' }}>
                    Timeline differs from target by more than 10s. You can still regenerate.
                  </p>
                )}
                <p className="footer-hint" style={{ marginBottom: '0.75rem' }}>
                  Edit scene text, keywords, or durations, then regenerate with new AI images aligned to your edits.
                  You can add, duplicate, or remove scenes to split narration or reuse an image. Image previews reflect the
                  latest render.
                </p>
                <div className="scene-timeline">
                  <div className="scene-timeline-track">
                    {editedScenes.map((scene, listIdx) => (
                      <div key={scene.index} className="scene-card">
                        <div className="scene-card-header">
                          <div className="scene-title">
                            Scene {scene.index} · {scene.duration_seconds.toFixed(1)}s
                          </div>
                          <div
                            className="scene-card-actions"
                            style={{ flexWrap: 'wrap', gap: '0.25rem', justifyContent: 'flex-end' }}
                          >
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => moveScene(scene.index, 'up')}
                              disabled={listIdx === 0}
                            >
                              Move Left
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => moveScene(scene.index, 'down')}
                              disabled={listIdx === editedScenes.length - 1}
                            >
                              Move Right
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => addSceneAfter(scene.index)}
                              disabled={loading}
                            >
                              Add scene after
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => duplicateSceneAfter(scene.index)}
                              disabled={loading}
                            >
                              Duplicate
                            </button>
                            <button
                              type="button"
                              className="tiny-button"
                              onClick={() => removeSceneFromEditor(scene.index)}
                              disabled={loading || editedScenes.length <= 1}
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                        {scene.image_url ? (
                          <div className="scene-preview">
                            <img
                              alt={`Scene ${scene.index}`}
                              src={`${API_BASE_URL}${scene.image_url}?v=${videoVersion}`}
                            />
                          </div>
                        ) : (
                          <div className="scene-preview scene-preview--placeholder">No image preview yet</div>
                        )}
                        <textarea
                          className="textarea"
                          rows={5}
                          value={scene.text}
                          onChange={e => updateScene(scene.index, { text: e.target.value })}
                        />
                        <div className="field-label" style={{ marginTop: '0.15rem' }}>
                          Image guidance keywords
                        </div>
                        <p className="footer-hint" style={{ marginTop: '0.2rem', marginBottom: '0.2rem' }}>
                          {result.used_ai
                            ? 'Used to guide regenerated AI images for this scene.'
                            : 'Used only if you choose Generate AI image for this scene.'}
                        </p>
                        <input
                          className="input"
                          value={scene.keywords.join(', ')}
                          onChange={e => {
                            const kws = e.target.value
                              .split(',')
                              .map(s => s.trim())
                              .filter(Boolean)
                            updateScene(scene.index, {
                              keywords: kws.length ? kws : ['scene'],
                            })
                          }}
                        />
                        <div className="field-label" style={{ marginTop: '0.35rem' }}>
                          Duration (seconds)
                        </div>
                        <input
                          className="input"
                          type="number"
                          min={1}
                          step={0.5}
                          value={scene.duration_seconds}
                          onChange={e =>
                            updateScene(scene.index, {
                            duration_seconds: roundToHalfSecond(
                              Number.parseFloat(e.target.value.replace(',', '.')) || 5,
                            ),
                            })
                          }
                        />
                        {!result.used_ai && (
                          <div style={{ marginTop: '0.5rem' }}>
                            <div className="field-label">Replace scene image</div>
                            <input
                              key={`replace-scene-${scene.index}-${videoVersion}`}
                              type="file"
                              accept="image/*"
                              className="input"
                              onChange={e => {
                                const f = e.target.files?.[0]
                                updateReplacementUploadForScene(scene.index, f)
                              }}
                            />
                            <p className="footer-hint" style={{ marginTop: '0.2rem' }}>
                              Select a new image, then regenerate the video.
                            </p>
                            {replacementPreviewUrls[scene.index] ? (
                              <div className="scene-preview" style={{ marginTop: '0.35rem', maxHeight: 140 }}>
                                <img
                                  alt={`Replacement preview scene ${scene.index}`}
                                  src={replacementPreviewUrls[scene.index]}
                                  style={{ maxHeight: 130, objectFit: 'contain', width: '100%' }}
                                />
                              </div>
                            ) : null}
                          </div>
                        )}
                        <div style={{ marginTop: '0.5rem' }}>
                          <button
                            type="button"
                            className="tiny-button"
                            onClick={() => void handlePreviewScene(scene.index)}
                            disabled={loading || scenePreviewLoadingIndex === scene.index}
                          >
                            {scenePreviewLoadingIndex === scene.index ? 'Rendering preview…' : 'Preview scene'}
                          </button>
                          {scenePreviewUrlByIndex[scene.index] ? (
                            <div style={{ marginTop: '0.45rem' }}>
                              <div className="field-label">Scene preview</div>
                              <video
                                key={`scpv-${scene.index}-${scenePreviewNonce}`}
                                controls
                                className="scene-preview-video"
                                src={`${API_BASE_URL}${scenePreviewUrlByIndex[scene.index]}?pv=${scenePreviewNonce}`}
                              />
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  className="button button-secondary full-width"
                  style={{ marginTop: '0.75rem' }}
                  onClick={handleRebuildFromScenes}
                  disabled={loading || !result || editedScenes.length === 0}
                >
                  <span className="button-icon">🎬</span>
                  {loading ? 'Regenerating…' : 'Regenerate video from scene edits'}
                </button>
              </section>
              )}

              <CollapsibleCard title="YouTube publishing" subtitle="Upload rendered video to YouTube" defaultOpen={false}>
                <div className="section-header-row" style={{ marginBottom: '0.5rem' }}>
                  <span className="status-text">
                    {youtubeChecking
                      ? 'Checking YouTube status...'
                      : youtubeConnected
                        ? 'Connected to YouTube'
                        : 'Not connected'}
                  </span>
                  <button
                    type="button"
                    className="tiny-button"
                    onClick={fetchYoutubeStatus}
                    disabled={youtubeChecking}
                  >
                    Refresh status
                  </button>
                </div>
                <div className="button-row" style={{ marginBottom: '0.75rem' }}>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={handleConnectYoutube}
                    disabled={youtubeChecking}
                  >
                    <span className="button-icon">📺</span>
                    {youtubeConnected ? 'Reconnect YouTube' : 'Connect YouTube'}
                  </button>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <input
                      className="input"
                      placeholder="YouTube title"
                      value={youtubeTitle}
                      onChange={e => setYoutubeTitle(e.target.value)}
                    />
                    <textarea
                      className="textarea"
                      placeholder="YouTube description"
                      value={youtubeDescription}
                      onChange={e => setYoutubeDescription(e.target.value)}
                      rows={3}
                    />
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                      <div className="field-label" style={{ marginBottom: 0 }}>
                        Privacy
                      </div>
                      <select
                        className="select"
                        value={youtubePrivacy}
                        onChange={e =>
                          setYoutubePrivacy(e.target.value as 'private' | 'unlisted' | 'public')
                        }
                      >
                        <option value="private">Private</option>
                        <option value="unlisted">Unlisted</option>
                        <option value="public">Public</option>
                      </select>
                      <button
                        type="button"
                        className="button"
                        onClick={handleUploadToYoutube}
                        disabled={youtubeUploading || loading || !result || !youtubeConnected}
                      >
                        <span className="button-icon">{youtubeUploading ? '⏳' : '📤'}</span>
                        {youtubeUploading ? 'Uploading…' : 'Upload to YouTube'}
                      </button>
                    </div>
                  </div>

                  {youtubeError && (
                    <div className="error" style={{ marginTop: '0.5rem' }}>
                      {youtubeError}
                    </div>
                  )}
                  {youtubeSuccessUrl && (
                    <p className="footer-hint" style={{ marginTop: '0.5rem' }}>
                      Uploaded to YouTube:{' '}
                      <a href={youtubeSuccessUrl} target="_blank" rel="noreferrer">
                        {youtubeSuccessUrl}
                      </a>
                    </p>
                  )}
              </CollapsibleCard>
            </>
          )}
          </main>
        </form>
      </div>
    </div>
  )
}