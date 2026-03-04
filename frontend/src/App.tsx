import React, { useState } from 'react'

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    setEditMode(false)
    setLoading(true)
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
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

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
                Turn a religious or spiritual topic into a short vertical explainer video.
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
              </div>
            </>
          )}

          {loading && (
            <div className="result-block">
              Generating script, images, and video… this depends on your machine and connection.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}