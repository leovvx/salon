/**
 * Agent run V2 — a card that follows an agent during one turn.
 * Inspired by Arc UI's "Agent run" block (observed behavior, original code):
 * - steps arrive by opening their height on a damped spring (no bounce);
 * - the current verb shimmers, then crossfades to the past tense (100 ms out, 160 ms in from 2 px);
 * - the check mark draws itself once; the header status uses the same fade; timer in tabular digits;
 * - a tool step expands in place (input / output in mono);
 * - the agent pauses on an approval (Allow / Deny with a note);
 * - at the end, the steps fold into one line and the sources appear below.
 */
import { memo, useEffect, useId, useLayoutEffect, useRef, useState } from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import {
  ChevronDown, FileDiff, FilePen, FileText, Globe, Hand, ListTodo, MessageSquareText, Search, Sparkles, SquareTerminal, X,
} from "lucide-react"
import { Shimmer } from "@/components/ai-elements/shimmer"
import { cn } from "@/lib/utils"
import { favicon, fmtClock, fmtDur, host, plural } from "./format"

export type Source = { url: string; title?: string; snippet?: string }
export type Mark = "think" | "read" | "search" | "fetch" | "terminal" | "write" | "plan" | "review" | "reply"
export type RunStep = {
  id: string
  mark: Mark
  verb: string          // in progress: "Searching"
  doneVerb: string      // finished: "Searched"
  target?: string       // "rate limit middleware"
  status: "running" | "waiting" | "done" | "denied"
  secs?: number
  meta?: string         // "5 results"
  sources?: Source[]
  io?: { input?: string; output?: string; lang?: "bash" | "text" }
  body?: React.ReactNode // custom expanded content
  approval?: { kind: "bash" | "write"; path?: string; content?: string; cmd?: string; onApprove: () => void; onReject: (reason: string) => void }
  reason?: string
}
export type RunStatus = "working" | "waiting" | "done"

const spring = { type: "spring", stiffness: 520, damping: 46, mass: 1 } as const // critically damped, no bounce
const swapOut = { duration: 0.1, ease: [0.4, 0, 1, 1] } as const
const swapIn = { duration: 0.16, ease: [0, 0, 0.2, 1] } as const

const ICONS: Record<Mark, typeof Search> = {
  think: Sparkles, read: FileText, search: Search, fetch: Globe, terminal: SquareTerminal,
  write: FilePen, plan: ListTodo, review: FileDiff, reply: MessageSquareText,
}

/* ------------------------------------------------------------------ */
/* small building blocks                                              */
/* ------------------------------------------------------------------ */

/** Crossfades text; the width follows the measured new text. */
export function Swap({ k, children, className }: { k: string; children: React.ReactNode; className?: string }) {
  const reduce = useReducedMotion()
  const ref = useRef<HTMLSpanElement>(null)
  const [w, setW] = useState<number | "auto">("auto")
  useLayoutEffect(() => { if (ref.current) setW(ref.current.offsetWidth) }, [k])
  return (
    <motion.span className={cn("relative inline-flex overflow-hidden whitespace-nowrap align-bottom", className)}
      animate={{ width: w }} transition={reduce ? { duration: 0 } : spring}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span key={k} ref={ref} className="inline-flex items-center gap-1.5"
          initial={reduce ? false : { opacity: 0, y: 2 }} animate={{ opacity: 1, y: 0, transition: swapIn }}
          exit={reduce ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, transition: swapOut }}>
          {children}
        </motion.span>
      </AnimatePresence>
    </motion.span>
  )
}

/** Check mark that draws its stroke only once. */
export function DrawnCheck({ className }: { className?: string }) {
  const reduce = useReducedMotion()
  return (
    <svg viewBox="0 0 16 16" fill="none" className={cn("size-3.5 text-emerald-500 dark:text-emerald-400", className)} aria-hidden>
      <motion.path d="M3.5 8.5l3 3 6-7" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
        initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.32, ease: [0.65, 0, 0.35, 1] }} />
    </svg>
  )
}

/** Opens/closes in height on the damped spring. */
export function Reveal({ open, children, className }: { open: boolean; children: React.ReactNode; className?: string }) {
  const reduce = useReducedMotion()
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div className={cn("overflow-hidden", className)}
          initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
          exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }} transition={reduce ? { duration: 0 } : { height: spring, opacity: { duration: 0.16 } }}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Favicon stack + counter, like "9 of 11 sources read". */
export function SourceStack({ sources, max = 5, label }: { sources: Source[]; max?: number; label?: string }) {
  const uniq = dedupe(sources)
  if (!uniq.length) return null
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="flex -space-x-1">
        {uniq.slice(0, max).map((s) => (
          <img key={s.url} src={favicon(s.url)} alt="" title={host(s.url)} loading="lazy"
            className="size-3.5 rounded-[3px] bg-white ring-1 ring-background" />
        ))}
      </span>
      {label && <span>{label}</span>}
    </span>
  )
}

export function dedupe(src: Source[]) {
  const seen = new Set<string>()
  return src.filter((s) => { const h = host(s.url); if (!s.url || seen.has(h)) return false; seen.add(h); return true })
}

/** List of consulted sources: one pill per site, hover = title + snippet. */
export function SourcesList({ sources }: { sources: Source[] }) {
  const uniq = dedupe(sources)
  return (
    <div className="flex flex-wrap gap-1.5">
      {uniq.map((s, i) => (
        <motion.a key={s.url} href={s.url} target="_blank" rel="noreferrer noopener" title={s.title || s.url}
          initial={{ opacity: 0, y: 2 }} animate={{ opacity: 1, y: 0 }} transition={{ ...swapIn, delay: i * 0.03 }}
          className="group/src inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-neutral-900/8 bg-neutral-900/[0.03] py-0.5 pr-2.5 pl-1 text-[12px] text-muted-foreground transition-colors hover:border-neutral-900/15 hover:text-foreground dark:border-neutral-100/10 dark:bg-neutral-100/[0.04] dark:hover:border-neutral-100/20">
          <img src={favicon(s.url)} alt="" className="size-4 rounded-full bg-white" />
          <span className="truncate">{s.title || host(s.url)}</span>
          <span className="shrink-0 opacity-50">{host(s.url)}</span>
        </motion.a>
      ))}
    </div>
  )
}

/** Timer that only runs while working. */
function useClock(startTs: number | undefined, endTs: number | undefined, ticking: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!ticking) return
    const id = setInterval(() => setNow(Date.now() / 1000), 250)
    return () => clearInterval(id)
  }, [ticking])
  if (!startTs) return 0
  return Math.max(0, (ticking ? now : endTs ?? now) - startTs)
}

/* ------------------------------------------------------------------ */
/* step                                                                */
/* ------------------------------------------------------------------ */

const StepRow = memo(function StepRow({ s }: { s: RunStep }) {
  const [open, setOpen] = useState(false)
  const reduce = useReducedMotion()
  const panelId = useId()
  const Icon = s.status === "waiting" ? FileDiff : ICONS[s.mark]
  const live = s.status === "running"
  const canOpen = !!(s.io?.input || s.io?.output || s.body || (s.sources && s.sources.length))
  const verb = s.status === "denied" ? "Denied" : s.status === "waiting" ? (s.approval?.kind === "bash" ? "Approve command" : "Approve writing") : live ? s.verb : s.doneVerb
  const label = (
    <span className="flex min-w-0 items-baseline gap-1.5">
      {/* verb: shimmers in the present, then crossfades to the past (100 ms out / 160 ms in, width tracked) */}
      <Swap k={verb} className={cn("shrink-0 font-medium", s.status === "waiting" ? "text-foreground" : live ? "text-foreground" : "text-muted-foreground")}>
        {live ? <Shimmer as="span" duration={1.5} spread={2.5}>{verb}</Shimmer> : <span>{verb}</span>}
      </Swap>
      {s.target && (
        <span className={cn("min-w-0 truncate transition-colors", live || s.status === "waiting" ? "text-foreground/90" : "text-muted-foreground",
          (s.mark === "read" || s.mark === "write" || s.mark === "terminal") && "font-mono text-[12px]")}>{s.target}</span>
      )}
    </span>
  )
  return (
    <motion.li layout="position" className="list-none"
      initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
      transition={reduce ? { duration: 0 } : { height: spring, opacity: { duration: 0.2, delay: 0.04 } }}>
      <button type="button" disabled={!canOpen} aria-expanded={canOpen ? open : undefined} aria-controls={canOpen ? panelId : undefined}
        onClick={() => setOpen((o) => !o)}
        className={cn("group/step relative flex w-full items-center gap-2.5 rounded-lg px-2 py-[6px] text-left text-[13px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/50",
          live ? "bg-neutral-900/[0.045] dark:bg-neutral-100/[0.05]" : "enabled:hover:bg-neutral-900/[0.03] dark:enabled:hover:bg-neutral-100/[0.03]")}>
        {/* the current task: accent stripe pulsing on the left edge */}
        {live && <motion.span aria-hidden className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-sky-400"
          animate={reduce ? {} : { opacity: [0.35, 1, 0.35] }} transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }} />}
        <span className="relative grid size-3.5 shrink-0 place-items-center">
          <Icon className={cn("size-3.5", s.status === "waiting" ? "text-amber-500" : s.status === "denied" ? "text-red-400" : live ? "text-sky-400" : "text-muted-foreground")} strokeWidth={1.8} />
          {live && <motion.span aria-hidden className="absolute inset-0 rounded-full ring-1 ring-sky-400/50"
            animate={reduce ? {} : { scale: [1, 1.9], opacity: [0.5, 0] }} transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }} />}
        </span>
        <span className="min-w-0 flex-1">{label}</span>
        {s.sources && s.sources.length > 0 && <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline"><SourceStack sources={s.sources} max={4} label={s.meta} /></span>}
        {!s.sources?.length && s.meta && <span className="hidden shrink-0 text-[11px] text-muted-foreground tabular-nums sm:inline">{s.meta}</span>}
        <span className="hidden w-14 shrink-0 text-right text-[11px] text-muted-foreground tabular-nums sm:inline">{s.status === "done" || s.status === "denied" ? fmtDur(s.secs) : ""}</span>
        <span className="grid size-3.5 shrink-0 place-items-center">
          {s.status === "done" && <DrawnCheck />}
          {s.status === "denied" && <X className="size-3.5 text-red-400" />}
          {live && <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60" />}
        </span>
        <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-[transform,opacity] duration-200", open && "rotate-180", !canOpen && "opacity-0")} />
      </button>
      {s.status === "denied" && s.reason && <p className="pb-1 pl-7 text-[12px] text-red-400/90">Sent back: {s.reason}</p>}
      <Reveal open={open && canOpen}>
        <div id={panelId} className="pb-2 pl-7 pr-1">
          {s.body}
          {s.io?.input && <Mono label="input">{s.io.input}</Mono>}
          {s.io?.output && <Mono label="output">{s.io.output}</Mono>}
          {s.sources && s.sources.length > 0 && <div className="mt-1.5"><SourcesList sources={s.sources} /></div>}
        </div>
      </Reveal>
      {s.status === "waiting" && s.approval && <Approval a={s.approval} target={s.target} />}
    </motion.li>
  )
})

function Mono({ label, children }: { label: string; children: string }) {
  return (
    <div className="mt-1.5 overflow-hidden rounded-md border border-neutral-900/8 dark:border-neutral-100/10">
      <div className="border-b border-neutral-900/8 bg-neutral-900/[0.03] px-2.5 py-1 text-[10px] tracking-wider text-muted-foreground uppercase dark:border-neutral-100/10 dark:bg-neutral-100/[0.03]">{label}</div>
      <pre className="max-h-64 overflow-auto px-2.5 py-2 font-mono text-[11.5px]/[18px] whitespace-pre text-muted-foreground">{children}</pre>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* approval: unified-style diff + Allow / Deny with a note             */
/* ------------------------------------------------------------------ */

function Approval({ a, target }: { a: NonNullable<RunStep["approval"]>; target?: string }) {
  const [note, setNote] = useState<string | null>(null)
  const rejectRef = useRef<HTMLButtonElement>(null)
  const lines = a.kind === "write" ? (a.content ?? "").split("\n") : [`$ ${a.cmd ?? target ?? ""}`]
  return (
    <div className="pb-2 pl-7">
      <div className="overflow-hidden rounded-lg border border-neutral-900/10 dark:border-neutral-100/10">
        <div className="flex items-center gap-2 border-b border-neutral-900/8 px-2 py-1.5 dark:border-neutral-100/10">
          <span className="rounded-md bg-neutral-900/[0.05] px-2 py-0.5 font-mono text-[12px] dark:bg-neutral-100/[0.07]">
            {a.kind === "write" ? (a.path?.split("/").pop() ?? "file") : "terminal"}
          </span>
          {a.kind === "write" && <span className="font-mono text-[12px] text-emerald-500">+{lines.length}</span>}
          {a.kind === "write" && a.path && <span className="ms-auto truncate text-[11px] text-muted-foreground" title={a.path}>{a.path}</span>}
        </div>
        <div className="max-h-72 overflow-auto font-mono text-[12px]/[20px]">
          {lines.map((l, i) => (
            <div key={i} className={cn("flex", a.kind === "write" ? "bg-emerald-500/[0.09]" : "bg-neutral-900/[0.02] dark:bg-neutral-100/[0.02]")}>
              <span className="w-9 shrink-0 pr-2 text-right text-muted-foreground/60 select-none">{i + 1}</span>
              {a.kind === "write" && <span aria-hidden className="w-4 shrink-0 text-emerald-500 select-none">+</span>}
              <span className="sr-only">{a.kind === "write" ? "Added: " : ""}</span>
              <span className="pr-3 whitespace-pre">{l || " "}</span>
            </div>
          ))}
        </div>
      </div>
      <motion.div layout transition={spring} className="mt-2">
        <AnimatePresence mode="popLayout" initial={false}>
          {note === null ? (
            <motion.div key="btns" className="flex flex-wrap items-center justify-end gap-1.5"
              initial={{ opacity: 0, y: 2 }} animate={{ opacity: 1, y: 0, transition: swapIn }} exit={{ opacity: 0, transition: swapOut }}>
              <span className="me-auto flex items-center gap-1.5 text-[12px] text-amber-600 dark:text-amber-400"><Hand className="size-3.5" />waiting for your approval</span>
              <button ref={rejectRef} type="button" onClick={() => setNote("")}
                className="h-7 rounded-md border border-neutral-900/10 px-3 text-[12px] hover:bg-neutral-900/[0.04] max-[520px]:flex-1 dark:border-neutral-100/12 dark:hover:bg-neutral-100/[0.05]">Deny</button>
              <button type="button" onClick={a.onApprove}
                className="h-7 rounded-md bg-foreground px-3 text-[12px] font-medium text-background hover:opacity-90 max-[520px]:flex-1">Allow</button>
            </motion.div>
          ) : (
            <motion.form key="note" className="flex items-center gap-1.5"
              initial={{ opacity: 0, y: 2 }} animate={{ opacity: 1, y: 0, transition: swapIn }} exit={{ opacity: 0, transition: swapOut }}
              onSubmit={(e) => { e.preventDefault(); a.onReject(note) }}>
              <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why? (the agent gets your note)"
                onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); setNote(null); requestAnimationFrame(() => rejectRef.current?.focus()) } }}
                className="h-7 min-w-0 flex-1 rounded-md border border-neutral-900/10 bg-transparent px-2.5 text-[12px] outline-none focus:border-neutral-900/25 dark:border-neutral-100/12 dark:focus:border-neutral-100/25" />
              <button type="submit" className="h-7 rounded-md bg-red-500/90 px-3 text-[12px] font-medium text-white hover:bg-red-500">Send back</button>
            </motion.form>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* card                                                                */
/* ------------------------------------------------------------------ */

export function AgentRun({
  title, avatar, model, status, steps, startTs, endTs, live, sources = [], summary, onStop,
}: {
  title: React.ReactNode
  avatar?: React.ReactNode
  model?: string
  status: RunStatus
  steps: RunStep[]
  startTs?: number
  endTs?: number
  live?: React.ReactNode        // live content (reply being written…)
  sources?: Source[]
  summary?: string              // folded line: "Thought for 2 min, 3 searches"
  onStop?: () => void
}) {
  const elapsed = useClock(startTs, endTs, status === "working")
  const running = steps.find((s) => s.status === "running")
  const current = running ? { verb: running.verb, target: running.target } : undefined
  const [unfold, setUnfold] = useState(false)
  const folded = status === "done" && !unfold
  const uniq = dedupe(sources)
  const statusEl =
    status === "working" ? { k: "w", el: <><span className="size-1.5 animate-pulse rounded-full bg-sky-400" /><Shimmer as="span" duration={1.6}>Working</Shimmer></> }
      : status === "waiting" ? { k: "a", el: <><Hand className="size-3.5 text-amber-500" />Waiting for you</> }
        : { k: "d", el: <><DrawnCheck />Done</> }
  return (
    <section aria-label={typeof title === "string" ? title : "Agent turn"}
      className="my-1 w-full max-w-[720px] overflow-hidden rounded-xl border border-neutral-900/8 bg-neutral-900/[0.015] dark:border-neutral-100/10 dark:bg-neutral-100/[0.02]">
      <header className="flex items-center gap-2 px-3 pt-2.5 pb-2">
        {avatar}
        <span className="min-w-0 truncate text-[13px] font-medium">{title}</span>
        {model && <span className="hidden truncate text-[12px] text-muted-foreground sm:inline">{model}</span>}
        {/* current task, always visible while working: a shimmering "Searching rate limit…" */}
        {current && status === "working" && (
          <span className="ms-auto hidden min-w-0 items-center gap-1.5 text-[12px] sm:flex">
            <Swap k={current.verb + (current.target ?? "")}>
              <Shimmer as="span" duration={1.5} className="truncate">{`${current.verb}${current.target ? ` ${current.target}` : "…"}`}</Shimmer>
            </Swap>
          </span>
        )}
        <span className={cn("flex items-center gap-2 text-[12px] text-muted-foreground", !(current && status === "working") && "ms-auto")}>
          <Swap k={statusEl.k} className="text-foreground/80">{statusEl.el}</Swap>
          {(elapsed >= 0.5 || status !== "done") && <span className="w-10 text-right tabular-nums">{fmtClock(elapsed)}</span>}
          {status === "working" && onStop && (
            <button type="button" onClick={onStop} title="Stop" className="grid size-6 place-items-center rounded-md hover:bg-neutral-900/[0.05] dark:hover:bg-neutral-100/[0.06]">
              <span className="size-2 rounded-[1px] bg-current" />
            </button>
          )}
        </span>
      </header>

      {/* folded line at the end of the turn */}
      <AnimatePresence initial={false}>
        {status === "done" && (
          <motion.button type="button" key="fold" onClick={() => setUnfold((u) => !u)} aria-expanded={unfold}
            initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ height: spring, opacity: { duration: 0.16 } }}
            className="flex w-full items-center gap-2 border-t border-neutral-900/6 px-3 py-2 text-left text-[13px] text-muted-foreground hover:text-foreground dark:border-neutral-100/8">
            <span className="min-w-0 flex-1 truncate">{summary}</span>
            {uniq.length > 0 && <span className="text-[11px]"><SourceStack sources={uniq} label={plural(uniq.length, "1 source", "# sources")} /></span>}
            {elapsed >= 0.5 && <span className="text-[11px] tabular-nums">{fmtDur(elapsed)}</span>}
            <ChevronDown className={cn("size-3.5 transition-transform duration-200", unfold && "rotate-180")} />
          </motion.button>
        )}
      </AnimatePresence>

      <Reveal open={!folded}>
        <ol aria-label="Steps" className="border-t border-neutral-900/6 px-2 py-1.5 dark:border-neutral-100/8">
          {steps.map((s) => <StepRow key={s.id} s={s} />)}
          {steps.length === 0 && status !== "done" && (
            <li className="flex items-center gap-2.5 px-1 py-[5px] text-[13px]">
              <Sparkles className="size-3.5 text-muted-foreground" strokeWidth={1.8} /><Shimmer as="span" duration={1.6}>Getting to work…</Shimmer>
            </li>
          )}
        </ol>
      </Reveal>

      <Reveal open={!!live}>
        <div className="border-t border-neutral-900/6 px-3 py-2 dark:border-neutral-100/8">{live}</div>
      </Reveal>

      <Reveal open={status === "done" && uniq.length > 0}>
        <div className="border-t border-neutral-900/6 px-3 pt-2 pb-2.5 dark:border-neutral-100/8">
          <div className="mb-1.5 text-[11px] tracking-wider text-muted-foreground uppercase">Sources consulted</div>
          <SourcesList sources={uniq} />
        </div>
      </Reveal>
    </section>
  )
}
