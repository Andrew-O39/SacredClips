import React, { useState, useEffect } from 'react'

const API_BASE_URL = 'http://localhost:8000'

type Scene = {
  index: number
  text: string
  keywords: string[]
  duration_seconds: number
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
  const [topic, setTopic] = useState('What is baptism in Christianity?')
  const [style, setStyle] = useState('neutral explainer, gentle and respectful tone')
  const [platform, setPlatform] = useState('tiktok')
  const [duration, setDuration] = useState(60)
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
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
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Request failed')
      }

      const data: VideoResponse = await res.json()
      setResult(data)
      setEditedScript(data.script_text)
      setVideoVersion(prev => prev + 1) // new video
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const handleRegenerateFromScript = async () => {
    if (!result) return
    setError(null)
    setLoading(true)
    setYoutubeError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/generate-video-from-script`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          style,
          platform,
          duration_seconds: duration,
          script_text: editedScript,
          scenes: result.scenes,
        }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || 'Request failed')
      }

      const data: VideoResponse = await res.json()
      setResult(data)
      setEditMode(false)
      setVideoVersion(prev => prev + 1) // new video, force reload
      setYoutubeTitle(topic)
      setYoutubeDescription(data.script_text)
      setYoutubeSuccessUrl(null)
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
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

          <form className="form" onSubmit={handleSubmit}>
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

            <div>
              <div className="field-label">Narration style</div>
              <textarea
                className="textarea"
                value={style}
                onChange={e => setStyle(e.target.value)}
              />
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

            <button className="button" type="submit" disabled={loading}>
              <span className="button-icon">{loading ? '⏳' : '✨'}</span>
              {loading ? 'Generating sacred clip…' : 'Generate video'}
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
                      onClick={handleRegenerateFromScript}
                      disabled={loading}
                    >
                      <span className="button-icon">🎬</span>
                      {loading ? 'Regenerating…' : 'Regenerate video from edited script'}
                    </button>
                  </div>
                ) : (
                  <div className="result-block">
                    {result.script_text}
                  </div>
                )}
              </div>

              <div>
                <div className="small-label">Scenes</div>
                <div className="result-block">
                  <ul className="scene-list">
                    {result.scenes.map(scene => (
                      <li key={scene.index}>
                        <div className="scene-title">
                          Scene {scene.index} · {scene.duration_seconds.toFixed(1)}s
                        </div>
                        <div>{scene.text}</div>
                        {scene.keywords.length > 0 && (
                          <div className="scene-keywords">
                            {scene.keywords.join(' · ')}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
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