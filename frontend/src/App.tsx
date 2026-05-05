import React, { useState, useEffect } from 'react'

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

type Scene = {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
  image_url?: string | null
}

type CreationMode = 'ai' | 'manual'

function scenesForApiPayload(scenes: Scene[]): {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
}[] {
  return scenes.map(s => ({
    index: s.index,
    text: s.text,
    keywords: s.keywords,
    duration_seconds: s.duration_seconds,
  }))
}

function splitScriptIntoScenes(script: string, targetTotalSeconds: number): Scene[] {
  const trimmed = script.trim()
  if (!trimmed) return []
  const blocks = trimmed.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean)
  const paragraphs = blocks.length ? blocks : [trimmed.replace(/\s+/g, ' ').trim()]
  const n = paragraphs.length
  const per = Math.max(8, targetTotalSeconds / n)
  return paragraphs.map((p, i) => ({
    index: i + 1,
    text: p.replace(/\n+/g, ' ').trim(),
    keywords: ['manual scene', `part ${i + 1}`],
    duration_seconds: per,
  }))
}

type VideoResponse = {
  video_path: string
  video_url: string
  script_text: string
  scenes: Scene[]
  used_ai: boolean
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
  const [topic, setTopic] = useState('What is baptism in Christianity?')
  const [style, setStyle] = useState('neutral explainer, gentle and respectful tone')
  const [platform, setPlatform] = useState('tiktok')
  const [duration, setDuration] = useState(60)
  const [visualStyle, setVisualStyle] = useState<VisualStyle>('Classical sacred art')
  const [editedScenes, setEditedScenes] = useState<Scene[]>([])
  const [manualUploads, setManualUploads] = useState<Record<number, File | undefined>>({})
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
  const totalSceneDuration = editedScenes.reduce((acc, s) => acc + (Number.isFinite(s.duration_seconds) ? s.duration_seconds : 0), 0)
  const durationDiff = Math.abs(totalSceneDuration - duration)
  const hasDurationWarning = durationDiff > 10

  const handleAiGenerate = async () => {
    setError(null)
    setResult(null)
    setEditMode(false)
    setLoading(true)
    setYoutubeError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/generate-video`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          style,
          platform,
          duration_seconds: duration,
          visual_style: visualStyle,
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Request failed')
      }

      const data: VideoResponse = await res.json()
      setResult(data)
      setEditedScript(data.script_text)
      setEditedScenes(data.scenes)
      setVideoVersion(prev => prev + 1) // new video
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
      setManualUploads({})
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const handleManualCreate = async () => {
    if (!editedScript.trim()) {
      setError('Paste a script (narration) for manual mode.')
      return
    }
    if (!editedScenes.length) {
      setError('Split your script into at least one scene, or edit scene cards.')
      return
    }
    setError(null)
    setResult(null)
    setLoading(true)
    setYoutubeError(null)
    try {
      const fd = new FormData()
      fd.append('topic', topic)
      fd.append('script_text', editedScript.trim())
      fd.append('scenes_json', JSON.stringify(scenesForApiPayload(editedScenes)))
      fd.append('visual_style', visualStyle)
      fd.append('platform', platform)
      fd.append('duration_seconds', String(duration))
      fd.append('style', style)

      for (const s of editedScenes) {
        const file = manualUploads[s.index]
        if (file) {
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
      setResult(data)
      setEditedScript(data.script_text)
      setEditedScenes(data.scenes)
      setEditMode(false)
      setVideoVersion(prev => prev + 1)
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
      setManualUploads({})
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
    setLoading(true)
    setYoutubeError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/generate-video-from-scenes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          style,
          platform,
          duration_seconds: duration,
          script_text: timelineScript,
          scenes: scenesForApiPayload(editedScenes),
          visual_style: visualStyle,
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Request failed')
      }

      const data: VideoResponse = await res.json()
      setResult(data)
      setEditMode(false)
      setEditedScript(data.script_text)
      setEditedScenes(data.scenes)
      setVideoVersion(prev => prev + 1) // new video, force reload
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
      setManualUploads({})
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
                duration_seconds: Math.max(15, duration / 4),
              },
            ],
      )
    }
  }

  const updateScene = (sceneIndex: number, patch: Partial<Scene>) => {
    setEditedScenes(prev => prev.map(sc => (sc.index === sceneIndex ? { ...sc, ...patch } : sc)))
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

  return (
    <div className="app-root">
      <div className="card">
        <div>
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

          <form className="form" onSubmit={handleFormSubmit}>
            <div>
              <div className="field-label">Creation mode</div>
              <div className="range-row">
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <input
                    type="radio"
                    name="creation-mode"
                    checked={creationMode === 'ai'}
                    onChange={() => handleCreationModeChange('ai')}
                  />
                  AI mode
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
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
                  required={creationMode === 'manual'}
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
                </div>
              </div>
            )}

            <div>
              <div className="field-label">Visual style {creationMode === 'ai' ? '(AI images)' : '(placeholders)'}</div>
              <select
                className="select"
                value={visualStyle}
                onChange={e => setVisualStyle(e.target.value as VisualStyle)}
                style={{ width: '100%' }}
              >
                {VISUAL_STYLE_OPTIONS.map(opt => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="field-label">Target duration (60–90 seconds)</div>
              <div className="range-row">
                <select
                  className="select"
                  value={platform}
                  onChange={e => setPlatform(e.target.value)}
                >
                  <option value="tiktok">TikTok</option>
                  <option value="instagram">Instagram Reels</option>
                  <option value="youtube_shorts">YouTube Shorts</option>
                </select>
                <div className="range-input">
                  <input
                    type="range"
                    min={60}
                    max={90}
                    step={5}
                    value={duration}
                    onChange={e => setDuration(Number(e.target.value))}
                    style={{ width: '100%' }}
                  />
                </div>
                <div className="range-value">{duration}s</div>
              </div>
            </div>

            {editedScenes.length > 0 && (creationMode === 'manual' && !result) && (
              <div>
                <div className="field-label">Scenes (before render)</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {editedScenes.map(scene => (
                    <div key={scene.index} className="result-block">
                      <div className="scene-title">Scene {scene.index}</div>
                      <textarea
                        className="textarea"
                        rows={3}
                        value={scene.text}
                        onChange={e => updateScene(scene.index, { text: e.target.value })}
                      />
                      <div className="field-label" style={{ marginTop: '0.35rem' }}>
                        Keywords (comma-separated)
                      </div>
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
                            duration_seconds:
                              Number.parseFloat(e.target.value.replace(',', '.')) || 5,
                          })
                        }
                      />
                      <div className="field-label" style={{ marginTop: '0.35rem' }}>
                        Image (optional)
                      </div>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={e => {
                          const f = e.target.files?.[0]
                          setManualUploads(prev => ({ ...prev, [scene.index]: f }))
                        }}
                      />
                      {manualUploads[scene.index] && (
                        <div style={{ marginTop: '0.5rem' }}>
                          <img
                            alt={`Scene ${scene.index} preview`}
                            src={URL.createObjectURL(manualUploads[scene.index]!)}
                            style={{ maxWidth: '100%', borderRadius: 8 }}
                          />
                        </div>
                      )}
                    </div>
                  ))}
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

            {error && <div className="error">{error}</div>}
          </form>
        </div>

        <div className="side-panel">
          <div className="side-header">
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

          {result && (
            <div
              className={`alert ${
                result.used_ai ? 'alert-success' : 'alert-warning'
              }`}
            >
              {result.used_ai ? (
                <>
                  <strong>AI mode:</strong> This clip uses AI-generated script, images, and narration.
                </>
              ) : (
                <>
                  <strong>Demo/manual mode:</strong> Script was edited or AI generation failed. Using your text and
                  placeholder/AI visuals.
                </>
              )}
            </div>
          )}

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

          {result && (
            <>
              <div>
                <div className="section-header-row">
                  <div className="small-label">Script</div>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
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
                  <div className="result-block">
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
                  <div className="result-block">
                    {result.script_text}
                  </div>
                )}
              </div>

              <div>
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
                  Image previews reflect the latest render.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {editedScenes.map((scene, listIdx) => (
                    <div key={scene.index} className="result-block">
                      <div className="scene-title">
                        Scene {scene.index} · {scene.duration_seconds.toFixed(1)}s
                      </div>
                      <div className="button-row" style={{ marginTop: '0.35rem', marginBottom: '0.5rem' }}>
                        <button
                          type="button"
                          className="tiny-button"
                          onClick={() => moveScene(scene.index, 'up')}
                          disabled={listIdx === 0}
                        >
                          Move Up
                        </button>
                        <button
                          type="button"
                          className="tiny-button"
                          onClick={() => moveScene(scene.index, 'down')}
                          disabled={listIdx === editedScenes.length - 1}
                        >
                          Move Down
                        </button>
                      </div>
                      {scene.image_url ? (
                        <div style={{ marginBottom: '0.5rem' }}>
                          <img
                            alt={`Scene ${scene.index}`}
                            src={`${API_BASE_URL}${scene.image_url}?v=${videoVersion}`}
                            style={{ width: '100%', maxHeight: 220, objectFit: 'cover', borderRadius: 8 }}
                          />
                        </div>
                      ) : (
                        <div
                          style={{
                            marginBottom: '0.5rem',
                            border: '1px dashed #9ca3af',
                            borderRadius: 8,
                            height: 120,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#6b7280',
                            background: '#f9fafb',
                          }}
                        >
                          No image preview yet
                        </div>
                      )}
                      <textarea
                        className="textarea"
                        rows={4}
                        value={scene.text}
                        onChange={e => updateScene(scene.index, { text: e.target.value })}
                      />
                      <div className="field-label" style={{ marginTop: '0.35rem' }}>
                        Keywords (comma-separated)
                      </div>
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
                            duration_seconds:
                              Number.parseFloat(e.target.value.replace(',', '.')) || 5,
                          })
                        }
                      />
                    </div>
                  ))}
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
              </div>

              <div>
                <div className="small-label">Preview</div>
                <div className="video-wrapper">
                  {result && (
                    <video
                      key={videoVersion} // force remount when version changes
                      controls
                      src={`${API_BASE_URL}${result.video_url}?v=${videoVersion}`} // cache-buster
                    />
                  )}
                </div>

                <div className="button-row">
                  <a
                    className="button button-secondary"
                    href={`${API_BASE_URL}${result.video_url}?v=${videoVersion}`}
                    download
                  >
                    <span className="button-icon">⬇️</span>
                    Download MP4
                  </a>
                </div>

                <p className="footer-hint">
                  Video is rendered on your backend and served from <code>{result.video_url}</code>. You can download it
                  as an MP4 and upload to TikTok, Instagram, or YouTube.
                </p>

                <div style={{ marginTop: '1.5rem' }}>
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
                  <div className="result-block">
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
                </div>
              </div>
            </>
          )}

          {loading && (
            <div className="result-block">
              <div style={{ marginBottom: "10px", fontWeight: 600 }}>
                Generating your video...
              </div>

              <div style={{ fontSize: "0.9rem", marginBottom: "10px" }}>
                Creating script, images, narration, and rendering the final video.
              </div>

              <div
                style={{
                  width: "100%",
                  height: "6px",
                  background: "#e5e7eb",
                  borderRadius: "4px",
                  overflow: "hidden"
                }}
              >
                <div
                  style={{
                    width: "100%",
                    height: "100%",
                    background: "#6366f1",
                    animation: "loading-bar 2s linear infinite"
                  }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}