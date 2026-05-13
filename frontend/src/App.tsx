import React, { useState, useEffect, useRef } from 'react'

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

type CreationMode = 'ai' | 'manual'
type ManualImageMode = 'upload' | 'generate' | 'placeholder'
type ManualNarrationSource = 'tts' | 'upload'
type GenerationProfile = 'ai' | 'manual_tts' | 'manual_upload' | 'regenerate'
type ImageFitMode = 'fit' | 'fill'

type BackgroundMusic = 'none' | 'peaceful_piano' | 'ambient_pad' | 'soft_strings' | 'gentle_choir'

type MotionEffect = 'none' | 'gentle_zoom' | 'slow_pan' | 'ken_burns'

type MotionIntensity = 'subtle' | 'medium' | 'strong'

type SubtitleStyle = 'off' | 'minimal' | 'cinematic' | 'shorts'

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

export const App: React.FC = () => {
  const [creationMode, setCreationMode] = useState<CreationMode>('ai')
  const [videoType, setVideoType] = useState<VideoType>('normal')
  const [topic, setTopic] = useState('What is baptism in Christianity?')
  const [style, setStyle] = useState('neutral explainer, gentle and respectful tone')
  const [aspectRatio, setAspectRatio] = useState<AspectRatio>('16:9')
  const [duration, setDuration] = useState(180)
  const [visualStyle, setVisualStyle] = useState<VisualStyle>('Classical sacred art')
  const [imageFitMode, setImageFitMode] = useState<ImageFitMode>('fit')
  const [backgroundMusic, setBackgroundMusic] = useState<BackgroundMusic>('none')
  const [backgroundMusicVolume, setBackgroundMusicVolume] = useState(0.12)
  const [motionEffect, setMotionEffect] = useState<MotionEffect>('gentle_zoom')
  const [motionIntensity, setMotionIntensity] = useState<MotionIntensity>('subtle')
  const [subtitleStyle, setSubtitleStyle] = useState<SubtitleStyle>('off')
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

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const musicPreviewRef = useRef<HTMLAudioElement | null>(null)
  const [uploadedAudioUrl, setUploadedAudioUrl] = useState('')
  const [uploadedAudioDuration, setUploadedAudioDuration] = useState(0)
  const [uploadedAudioCurrentTime, setUploadedAudioCurrentTime] = useState(0)
  const [sceneCutTimes, setSceneCutTimes] = useState<number[]>([])

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
  const totalSceneDuration = editedScenes.reduce((acc, s) => acc + (Number.isFinite(s.duration_seconds) ? s.duration_seconds : 0), 0)
  const durationDiff = Math.abs(totalSceneDuration - duration)
  const hasDurationWarning = durationDiff > 10
  const durationMin = videoType === 'normal' ? 120 : 60
  const durationMax = videoType === 'normal' ? 600 : 90
  const durationStep = videoType === 'normal' ? 30 : 5

  const beginGenerationProgress = (profile: GenerationProfile) => {
    setGenerationProfile(profile)
    setGenerationStage('Preparing request')
    setGenerationProgress(5)
  }

  const finishGenerationProgress = async () => {
    setGenerationStage('Complete')
    setGenerationProgress(100)
    await new Promise(resolve => setTimeout(resolve, 250))
  }

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

  const resetToNewVideo = () => {
    setResult(null)
    setEditedScript('')
    setEditedScenes([])
    setManualUploads({})
    setManualImageModes({})
    setManualAudioUpload(undefined)
    setPersistedManualNarration(null)
    clearReplacementUploadState()
    setVideoVersion(0)
    setYoutubeSuccessUrl(null)
    setYoutubeError(null)
    setError(null)
    setEditMode(false)
    setLoading(false)
    setGenerationStage('Idle')
    setGenerationProgress(0)
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
      const res = await fetch(`${API_BASE_URL}/generate-video`, {
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
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Request failed')
      }

      const data: VideoResponse = await res.json()
      await finishGenerationProgress()
      setResult(data)
      setEditedScript(data.script_text)
      setEditedScenes(data.scenes)
      setVideoVersion(prev => prev + 1) // new video
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
      setManualUploads({})
      setManualImageModes({})
      setPersistedManualNarration(null)
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
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

      const res = await fetch(`${API_BASE_URL}/manual-video`, {
        method: 'POST',
        body: fd,
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Manual video request failed')
      }

      const data: VideoResponse = await res.json()
      await finishGenerationProgress()
      setResult(data)
      setEditedScript(data.script_text)
      setEditedScenes(data.scenes)
      setEditMode(false)
      setVideoVersion(prev => prev + 1)
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
      setManualUploads({})
      setManualImageModes({})
      setManualAudioUpload(undefined)
      setPersistedManualNarration(
        data.narration_source === 'upload' && data.narration_audio_path
          ? { source: 'upload', path: data.narration_audio_path }
          : null,
      )
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (creationMode === 'ai') handleAiGenerate()
    else handleManualCreate()
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

      const applyRebuildSuccess = async (data: VideoResponse) => {
        await finishGenerationProgress()
        setResult(data)
        setEditMode(false)
        setEditedScript(data.script_text)
        setEditedScenes(data.scenes)
        setVideoVersion(prev => prev + 1) // new video, force reload
        setYoutubeTitle(topic)
        setYoutubeDescription(data.script_text)
        setYoutubeSuccessUrl(null)
        setManualUploads({})
        setManualImageModes({})
        setPersistedManualNarration(
          data.narration_source === 'upload' && data.narration_audio_path
            ? { source: 'upload', path: data.narration_audio_path }
            : null,
        )
        clearReplacementUploadState()
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

        const res = await fetch(`${API_BASE_URL}/manual-video`, {
          method: 'POST',
          body: fd,
        })

        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || 'Manual video request failed')
        }

        const data: VideoResponse = await res.json()
        await applyRebuildSuccess(data)
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

        const res = await fetch(`${API_BASE_URL}/generate-video-from-scenes`, {
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
          }),
        })

        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || 'Request failed')
        }

        const data: VideoResponse = await res.json()
        await applyRebuildSuccess(data)
      }
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const handleCreationModeChange = (m: CreationMode) => {
    setCreationMode(m)
    setError(null)
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
  }

  const addManualScene = () => {
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
  }

  /** Post-generation: remove scene if more than one remains; reindex. */
  const removeSceneFromEditor = (sceneIndex: number) => {
    setEditedScenes(prev => {
      if (prev.length <= 1) return prev
      return reindexScenes(prev.filter(s => s.index !== sceneIndex))
    })
    clearReplacementUploadState()
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
    if (!loading) return

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
  }, [loading, generationProfile])

  useEffect(() => {
    const el = musicPreviewRef.current
    if (!el) return
    el.volume = Math.min(1, Math.max(0, backgroundMusicVolume))
  }, [backgroundMusicVolume, backgroundMusic])

  useEffect(() => {
    const shouldPreview =
      creationMode === 'manual' && manualNarrationSource === 'upload' && manualAudioUpload != null

    if (!shouldPreview) {
      setUploadedAudioUrl('')
      setUploadedAudioDuration(0)
      setUploadedAudioCurrentTime(0)
      setSceneCutTimes([])
      return undefined
    }

    const url = URL.createObjectURL(manualAudioUpload)
    setUploadedAudioUrl(url)
    setSceneCutTimes([])
    setUploadedAudioDuration(0)
    setUploadedAudioCurrentTime(0)

    return () => {
      URL.revokeObjectURL(url)
    }
  }, [creationMode, manualNarrationSource, manualAudioUpload])

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
    <div className="app-shell">
      <div className="app-container">
        <div className="workspace-card">
          <div className="card-header">
            <div>
              <div className="badge">Religious video generator</div>
              <div className="title">
                <span className="title-accent" />
                SacredClips
              </div>
              <p className="subtitle">
                Turn a religious or spiritual topic into a short educational explainer video.
                Neutral, educational, and ready for TikTok, Reels, or Shorts.
              </p>
            </div>
          </div>

          <section className="status-panel" aria-live="polite">
            <div className="status-panel-header">
              <div>
                <div className="status-text">
                  {loading ? 'Generating' : result ? 'Ready' : 'Idle'} · Backend
                </div>
                <p className="secondary-text">
                  We keep things neutral and respectful. Review each clip before posting.
                </p>
              </div>
              <div className="status-dot" />
            </div>

            {loading && (
              <div className="editor-section">
                <div className="generation-progress-label">
                  {generationStage || 'Generating your video...'}
                </div>
                <div className="generation-progress-meta">
                  Estimated progress: {Math.floor(generationProgress)}%
                </div>
                <div className="generation-progress-bar">
                  <div
                    className="generation-progress-fill"
                    style={{ width: `${Math.max(5, Math.floor(generationProgress))}%` }}
                  />
                </div>
                <p className="footer-hint" style={{ marginTop: '0.6rem' }}>
                  This is an estimated progress indicator. Final rendering may take longer for longer videos.
                </p>
              </div>
            )}

            {error && <div className="error">{error}</div>}

            {!result && !loading && (
              <>
                <div className="pill-row">
                  <div className="pill">What is baptism in Christianity?</div>
                  <div className="pill">Basics of baptism</div>
                  <div className="pill">What is the Trinity?</div>
                  <div className="pill">What is a Sabbath?</div>
                </div>
                <p className="footer-hint">
                  Tip: ask for short explainers of holidays, practices, symbols, or concepts.
                  The app will not create political content or tell people what they should believe.
                </p>
              </>
            )}
          </section>

          <section className="editor-section editor-section--creation">
          <form className="form" onSubmit={handleFormSubmit}>
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
              </div>
              <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                AI generates script and images. Manual mode uses your pasted script, optional uploads per scene,
                TTS, and local rendering — no AI scriptwriter.
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
                      Uploaded narration will be used as the video audio track (TTS is skipped).
                    </p>
                    {manualAudioUpload && (
                      <div className="editor-section" style={{ marginTop: '1rem' }}>
                        <div className="field-label">Audio timing assistant</div>
                        <p className="footer-hint">
                          {
                            'Play your uploaded narration and click "Add scene cut here" whenever you want the image to change.'
                          }
                        </p>
                        <p className="footer-hint">
                          Scene durations are used as visual timing and will be scaled to the uploaded audio if
                          needed.
                        </p>
                        <div className="result-block result-block--expanded">
                          {uploadedAudioUrl ? (
                            <audio
                              key={uploadedAudioUrl}
                              ref={audioRef}
                              src={uploadedAudioUrl}
                              controls
                              onLoadedMetadata={syncAudioDurationFromElement}
                              onDurationChange={syncAudioDurationFromElement}
                              onTimeUpdate={syncAudioCurrentTimeFromElement}
                              onSeeking={syncAudioCurrentTimeFromElement}
                              onSeeked={syncAudioCurrentTimeFromElement}
                              className="timing-assistant-audio"
                            />
                          ) : (
                            <p className="footer-hint" style={{ marginTop: '0.5rem' }}>
                              Preparing audio preview…
                            </p>
                          )}
                          <div className="action-row" style={{ marginTop: '0.65rem' }}>
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
                            <div style={{ marginTop: '0.75rem' }}>
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
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

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
                {videoType === 'normal'
                  ? 'Output format: 16:9 horizontal'
                  : 'Output format: 9:16 vertical'}
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
                Fit full image: keeps the whole image visible, may add padding.
              </p>
              <p className="footer-hint" style={{ marginTop: '0.2rem' }}>
                Fill screen / crop: fills the frame, may crop image edges.
              </p>
            </div>

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
                  <p className="footer-hint">Keep volume low so narration remains clear.</p>
                  <audio
                    ref={musicPreviewRef}
                    key={backgroundMusic}
                    className="music-preview-audio"
                    controls
                    src={backgroundMusicPreviewUrl(backgroundMusic) ?? undefined}
                  />
                  <p className="footer-hint">
                    Preview uses the selected volume. Final video will mix music under narration.
                  </p>
                </>
              )}
            </div>

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
              <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                Adds subtle motion to still images. Ken Burns gently zooms and pans across the image.
              </p>
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
              <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                Controls how noticeable the image movement feels.
              </p>
            </div>

            <div>
              <div className="field-label">Subtitles</div>
              <select
                className="select input-full"
                value={subtitleStyle}
                onChange={e => setSubtitleStyle(e.target.value as SubtitleStyle)}
              >
                <option value="off">Off</option>
                <option value="minimal">Minimal</option>
                <option value="cinematic">Cinematic</option>
                <option value="shorts">Shorts style</option>
              </select>
              <p className="footer-hint" style={{ marginTop: '0.35rem' }}>
                Subtitles are split into readable chunks during each scene. Shorts and vertical (9:16) use shorter
                lines and up to three lines when needed. For best timing with uploaded narration, use shorter scene
                text or create more scene cuts where the spoken lines change.
              </p>
            </div>

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

            {editedScenes.length > 0 && creationMode === 'manual' && !result && (
              <div>
                <div className="field-label">Scenes (before render)</div>
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
                        <div className="field-label" style={{ marginTop: '0.35rem' }}>
                          Image source
                        </div>
                        <select
                          className="select input-full"
                          value={manualImageModes[scene.index] ?? (manualUploads[scene.index] ? 'upload' : 'placeholder')}
                          onChange={e =>
                            setManualImageModes(prev => ({
                              ...prev,
                              [scene.index]: e.target.value as ManualImageMode,
                            }))
                          }
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
                                setManualUploads(prev => ({ ...prev, [scene.index]: f }))
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
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <button className="button" type="submit" disabled={loading}>
              <span className="button-icon">{loading ? '⏳' : '✨'}</span>
              {loading
                ? creationMode === 'ai'
                  ? 'Generating sacred clip…'
                  : 'Building manual clip…'
                : creationMode === 'ai'
                  ? 'Generate video'
                  : 'Create manual video'}
            </button>
          </form>
          </section>

          {result && (
            <>
              <section className="editor-section">
                <div
                  className={`alert ${
                    result.used_ai ? 'alert-success' : 'alert-warning'
                  }`}
                >
                  {result.used_ai ? (
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
              </section>

              <section className="editor-section editor-section--preview">
                <div className="small-label">Preview</div>
                <div className="video-wrapper">
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
                  Video is rendered on your backend and served from <code>{result.video_url}</code>. You can download it
                  as an MP4 and upload to TikTok, Instagram, or YouTube.
                </p>
              </section>

              <section className="editor-section">
                <div className="section-header-row">
                  <div className="small-label">Script</div>
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

              <section className="editor-section">
                <div className="section-header-row">
                  <div className="small-label">Scene editor</div>
                </div>
                <p className="footer-hint" style={{ marginBottom: '0.35rem' }}>
                  Total timeline duration: {totalSceneDuration.toFixed(1)}s · Target: {duration.toFixed(1)}s
                </p>
                {hasDurationWarning && (
                  <p className="footer-hint" style={{ color: '#b45309', marginBottom: '0.6rem' }}>
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

              <section className="editor-section editor-section--youtube">
                <div className="section-header-row">
                  <div className="small-label">YouTube Shorts</div>
                  <div className="status-text">
                    {youtubeChecking
                      ? 'Checking YouTube status...'
                      : youtubeConnected
                        ? 'Connected to YouTube'
                        : 'Not connected'}
                  </div>
                </div>
                <div className="result-block result-block--expanded">
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
                    <button
                      type="button"
                      className="tiny-button"
                      onClick={fetchYoutubeStatus}
                      disabled={youtubeChecking}
                    >
                      Refresh status
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
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}