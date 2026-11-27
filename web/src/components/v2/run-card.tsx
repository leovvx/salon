/** Adapts Salon events (thought / tool / delta) to the Agent run card. */
import { memo } from "react"
import { Circle, CircleCheck } from "lucide-react"
import { MessageResponse } from "@/components/ai-elements/message"
import { Shimmer } from "@/components/ai-elements/shimmer"
import { post } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Ag, Live, Step, Task, Thought, Tool } from "@/views/room"
import { AgentRun, type RunStatus, type RunStep, type Source } from "./agent-run"
import { fmtDur, host, plural } from "./format"

/** Last complete sentence of the current thought: "what it is thinking about". */
export function headline(t: string) {
  const s = t.trim().replace(/\s+/g, " ")
  if (!s) return ""
  const parts = s.split(/(?<=[.!?…])\s+/)
  const done = parts.length > 1 ? parts[parts.length - 2] : parts[0]
  const pick = done.length > 12 ? done : parts[parts.length - 1]
  return pick.length > 110 ? pick.slice(0, 107) + "…" : pick
}

const short = (x: unknown, n = 90) => { const s = String(x ?? "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s }

function toolStep(t: Tool): RunStep {
  const st: RunStep["status"] = t.state === "approval" ? "waiting" : t.state === "denied" ? "denied" : t.state === "running" ? "running" : "done"
  const secs = t.ms != null ? t.ms / 1000 : undefined
  const base = { id: t.id, status: st, secs, reason: t.reason }
  const approval = st === "waiting" ? {
    onApprove: () => post("/api/room/approve", { id: t.id, ok: true }),
    onReject: (reason: string) => post("/api/room/approve", { id: t.id, ok: false, reason }),
  } : undefined
  switch (t.name) {
    case "web_search": {
      const src = t.sources ?? []
      return { ...base, mark: "search", verb: "Searching", doneVerb: "Searched", target: short(t.args.query),
        meta: st === "done" ? plural(src.length, "1 result", "# results") : undefined, sources: src,
        io: src.length ? undefined : { output: t.output } }
    }
    case "web_fetch": {
      const u = String(t.args.url ?? "")
      return { ...base, mark: "fetch", verb: "Reading page", doneVerb: "Read", target: host(u),
        sources: t.sources ?? (u ? [{ url: u }] : []), io: { input: u, output: t.output } }
    }
    case "read_file":
      return { ...base, mark: "read", verb: "Reading", doneVerb: "Read", target: String(t.args.path ?? ""), io: { output: t.output } }
    case "write_file":
      return { ...base, mark: "write", verb: "Writing", doneVerb: "Wrote", target: String(t.args.path ?? ""),
        meta: st === "done" ? `+${String(t.args.content ?? "").split("\n").length} lines` : undefined,
        io: { input: String(t.args.content ?? ""), output: t.output },
        approval: approval && { kind: "write", path: String(t.args.path ?? ""), content: String(t.args.content ?? ""), ...approval } }
    case "bash":
      return { ...base, mark: "terminal", verb: "Running", doneVerb: "Ran", target: short(t.args.cmd, 70),
        io: { input: String(t.args.cmd ?? ""), output: t.output },
        approval: approval && { kind: "bash", cmd: String(t.args.cmd ?? ""), ...approval } }
    case "plan": {
      const items = (t.args.items as Task[]) || []
      return { ...base, mark: "plan", verb: "Updating tasks", doneVerb: "Updated tasks",
        meta: `${items.filter((i) => i.done).length}/${items.length}`, body: <Tasks tasks={items} /> }
    }
    default:
      return { ...base, mark: "terminal", verb: `Using ${t.name}`, doneVerb: `Used ${t.name}`,
        io: { input: JSON.stringify(t.args, null, 2), output: t.output } }
  }
}

function thoughtStep(t: Thought): RunStep {
  return { id: t.id, mark: "think", verb: "Thinking", doneVerb: `Thought${t.secs ? " for " + fmtDur(t.secs) : ""}`,
    target: t.summary ?? headline(t.text), status: "done", secs: t.secs,
    meta: `${t.text.trim().split(/\s+/).length} words`,
    body: <p className="mt-1 max-h-64 overflow-auto rounded-md bg-neutral-900/[0.03] px-2.5 py-2 text-[12px]/[19px] whitespace-pre-wrap text-muted-foreground italic dark:bg-neutral-100/[0.03]">{t.text.trim()}</p> }
}

/** "Thought for 2 min, ran 3 searches, read 2 pages". */
function summarize(steps: Step[], silent: boolean) {
  const tools = steps.filter((s): s is Tool => s.type === "tool")
  const n = (name: string) => tools.filter((t) => t.name === name).length
  const thinkSecs = steps.reduce((a, s) => a + (s.type === "thought" ? s.secs ?? 0 : 0), 0)
  const parts: string[] = []
  if (steps.some((s) => s.type === "thought")) parts.push(`thought${thinkSecs ? " for " + fmtDur(thinkSecs) : ""}`)
  const p = (k: number, one: string, many: string) => k && parts.push(plural(k, one, many))
  p(n("web_search"), "ran 1 search", "ran # searches")
  p(n("web_fetch"), "read 1 page", "read # pages")
  p(n("bash"), "ran 1 command", "ran # commands")
  p(n("read_file"), "read 1 file", "read # files")
  p(n("write_file"), "wrote 1 file", "wrote # files")
  if (n("plan")) parts.push("updated tasks")
  const denied = tools.filter((t) => t.state === "denied").length
  p(denied, "1 action denied", "# actions denied")
  if (silent) parts.push("passed")
  const s = parts.join(", ") || "activity"
  return s[0].toUpperCase() + s.slice(1)
}

function Tasks({ tasks }: { tasks: Task[] }) {
  return (
    <ul className="mt-1 space-y-1 text-[12px]">
      {tasks.map((t, i) => (
        <li key={i} className={cn("flex items-start gap-2", t.done && "text-muted-foreground line-through")}>
          {t.done ? <CircleCheck className="mt-px size-3.5 shrink-0 text-emerald-500" /> : <Circle className="mt-px size-3.5 shrink-0 text-muted-foreground" />}
          <span>{t.text}</span>
        </li>
      ))}
    </ul>
  )
}

export const RunCard = memo(function RunCard({ name, model, color, steps, silent, live }: {
  agent: Ag; name: string; model: string; color: string; steps: Step[]; silent: boolean; live?: Live
}) {
  const run: RunStep[] = steps.map((s) => (s.type === "thought" ? thoughtStep(s) : toolStep(s)))
  // the live step: its thought being written, or its reply in progress
  if (live?.on && !run.some((r) => r.status === "running" || r.status === "waiting")) {
    if (live.content) run.push({ id: "live-reply", mark: "reply", verb: "Writing reply", doneVerb: "Replied", status: "running" })
    else run.push({ id: "live-think", mark: "think", verb: "Thinking", doneVerb: "Thought", status: "running",
      target: headline(live.thinking) || undefined, io: live.thinking ? { output: live.thinking } : undefined })
  }
  const status: RunStatus = run.some((r) => r.status === "waiting") ? "waiting" : live?.on ? "working" : "done"
  const starts = steps.map((s) => (s.type === "thought" ? s.ts - (s.secs ?? 0) : s.started ?? s.ts))
  const startTs = Math.min(...starts, live?.since ?? Infinity)
  const endTs = Math.max(...steps.map((s) => s.ts), 0)
  const sources: Source[] = steps.flatMap((s) => (s.type === "tool" ? s.sources ?? [] : []))
  return (
    <AgentRun
      title={name}
      avatar={<span className={cn("grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold", color)}>{name.slice(0, 1).toUpperCase()}</span>}
      model={model}
      status={status}
      steps={run}
      startTs={isFinite(startTs) ? startTs : undefined}
      endTs={endTs || undefined}
      sources={sources}
      summary={summarize(steps, silent)}
      onStop={() => post("/api/room/stop")}
      live={live?.on && live.content ? (
        <div className="text-[13px]/[20px] text-muted-foreground"><MessageResponse>{live.content}</MessageResponse></div>
      ) : live?.on && !steps.length && !live.thinking ? <Shimmer as="span" duration={1.4} className="text-[13px]">connecting to the model…</Shimmer> : undefined}
    />
  )
}, (a, b) => a.steps === b.steps && a.live === b.live && a.silent === b.silent && a.name === b.name && a.model === b.model)
