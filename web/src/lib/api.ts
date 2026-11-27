export type Msg = {
  role: string
  text: string
  reasoning?: string
  function?: string
  error?: string
  tool_calls?: { function: string; arguments: unknown }[]
}

export type LogEntry = {
  path: string
  task: string
  model?: string
  status: string
  created?: string
  samples?: number | null
  metrics?: Record<string, number>
  error?: string | null
}

export type SampleRow = {
  idx: number
  id: string | number
  epoch: number
  input: string
  scores: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type LogDetail = {
  eval: { task: string; model: string; task_args: unknown }
  status: string
  results?: { scores?: { name: string; metrics?: Record<string, { value: unknown }> }[] }
  samples: SampleRow[]
}

export type Sample = {
  id: string | number
  epoch: number
  target: unknown
  metadata: unknown
  usage: unknown
  error?: string | null
  messages: Msg[]
  scores: Record<string, { value: unknown; explanation?: string }>
  model_calls: {
    model: string
    role?: string
    input_len: number
    output?: Msg
    usage?: { total_tokens: number }
    time?: number
  }[]
}

export const get = async <T,>(url: string): Promise<T> => (await fetch(url)).json()
export const post = async <T,>(url: string, body?: unknown): Promise<T> =>
  (
    await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    })
  ).json()

/** Reads an SSE `data: …` stream from a POST. */
export async function* sse(res: Response) {
  const rd = res.body!.getReader()
  const dec = new TextDecoder()
  let buf = ""
  while (true) {
    const { value, done } = await rd.read()
    if (done) return
    buf += dec.decode(value, { stream: true })
    const parts = buf.split("\n\n")
    buf = parts.pop()!
    for (const p of parts) if (p.startsWith("data: ")) yield JSON.parse(p.slice(6))
  }
}

export const fmt = (v: unknown) =>
  typeof v === "number" ? +v.toFixed(3) : typeof v === "object" ? JSON.stringify(v) : String(v ?? "")
