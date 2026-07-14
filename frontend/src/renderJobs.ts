export type RenderJobStatusLiteral = 'queued' | 'running' | 'completed' | 'failed'

export type RenderJobStatus = {
  job_id: string
  job_type: string
  status: RenderJobStatusLiteral
  stage: string
  progress: number
  error?: string | null
  result?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued',
  preparing: 'Preparing',
  script: 'Generating script',
  images: 'Creating visuals',
  narration: 'Generating narration',
  rendering: 'Rendering video',
  finalizing: 'Finalizing',
  completed: 'Complete',
  failed: 'Failed',
  interrupted: 'Interrupted',
}

export function formatJobStage(stage: string): string {
  const key = stage.trim().toLowerCase()
  return STAGE_LABELS[key] ?? stage.replace(/_/g, ' ')
}

export async function fetchRenderJob(apiBase: string, jobId: string): Promise<RenderJobStatus> {
  const res = await fetch(`${apiBase}/jobs/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Failed to fetch job ${jobId}`)
  }
  return res.json() as Promise<RenderJobStatus>
}

export function pollRenderJob(
  apiBase: string,
  jobId: string,
  callbacks: {
    onUpdate: (job: RenderJobStatus) => void
    onComplete: (job: RenderJobStatus) => void
    onFailed: (job: RenderJobStatus) => void
    onError?: (err: Error) => void
  },
  intervalMs = 1500,
): () => void {
  let stopped = false
  let timer: number | undefined

  const tick = async () => {
    if (stopped) return
    try {
      const job = await fetchRenderJob(apiBase, jobId)
      if (stopped) return
      callbacks.onUpdate(job)
      if (job.status === 'completed') {
        stopped = true
        if (timer !== undefined) window.clearInterval(timer)
        callbacks.onComplete(job)
        return
      }
      if (job.status === 'failed') {
        stopped = true
        if (timer !== undefined) window.clearInterval(timer)
        callbacks.onFailed(job)
      }
    } catch (err) {
      if (!stopped) {
        callbacks.onError?.(err instanceof Error ? err : new Error(String(err)))
      }
    }
  }

  void tick()
  timer = window.setInterval(() => {
    void tick()
  }, intervalMs)

  return () => {
    stopped = true
    if (timer !== undefined) window.clearInterval(timer)
  }
}
