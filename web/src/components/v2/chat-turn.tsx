/**
 * Agent turn in the style of Arc UI's "AI chat" (behavior and measurements taken from the page, original code):
 * - no bubble: the reply is plain text, 15/24;
 * - the agent is recognized by its colored mark, placed on the "Thought for 4 s ›" line (13 px, gray);
 * - the thought unfolds below, 13/20.8, indented 16 px with a rule;
 * - each tool is a rounded pill (h 30, border, slightly raised background): icon, label, site marks, counter;
 * - the reply in progress is written word by word, each chunk fading in over 160 ms;
 * - actions under the reply: copy, reply, retry.
 */
import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { ChevronRight, Copy, Check, CornerUpLeft, FileText, Globe, RotateCw, Search } from "lucide-react"
import { toast } from "sonner"
import { MessageResponse } from "@/components/ai-elements/message"
import { Shimmer } from "@/components/ai-elements/shimmer"
import { cn } from "@/lib/utils"
import { Reveal, SourceStack, SourcesList, Swap, dedupe, type Source } from "./agent-run"
import { fmtDur, host, plural } from "./format"
import { AGENT_COLOR, AgentMark, type Who } from "./marks"

const LEAK_START = /^\s*(<think>|okay\b|ok,|alright|let me|let's|first,|hmm|so,|wait|the user|i need|i should|je dois|bon,|d'accord|alors,|voyons|l'utilisateur)/i

/** Splits off a thought that "leaked" into the text ("… </think> answer"). */
export function splitThink(text: string): { thought: string; answer: string } {
  if (!text.includes("</think>")) {
    // thought cut off before </think> (older messages): a long text that starts like reasoning
    if (text.length > 400 && LEAK_START.test(text)) return { thought: text.replace("<think>", "").trim(), answer: "" }
    return { thought: "", answer: text.replace(/^\s*<think>\s*/, "") }
  }
  const i = text.lastIndexOf("</think>")
  return { thought: text.slice(0, i).replace("<think>", "").trim(), answer: text.slice(i + 8).trim() }
}

/* ---------------- header line: mark + name + "Thought for 4 s ›" ---------------- */

/** Mark + name, placed before "Thought ›" on the same line. */
export function HeadLead({ who, name }: { who: Who; name: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5">
      <AgentMark who={who} label={name} className="size-3.5" />
      <span className={cn("text-[13px] font-medium", AGENT_COLOR[who])}>{name}</span>
      <span aria-hidden className="text-muted-foreground/50">·</span>
    </span>
  )
}

export function TurnHead({ who, name, time, children }: { who: Who; name: string; time?: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-h-7 items-center gap-1.5">
      <AgentMark who={who} label={name} className="size-3.5" />
      <span className={cn("text-[13px] font-medium", AGENT_COLOR[who])}>{name}</span>
      {children}
      {time && <span className="text-[12px] text-muted-foreground/70 tabular-nums">{time}</span>}
    </div>
  )
}

/** "Thought for 4 s ›" unfolds the thought; a shimmering "Thinking…" while it is being written. */
export function ThoughtToggle({ text, secs, live, summary, lead }: { text: string; secs?: number; live?: boolean; summary?: string | null; lead?: React.ReactNode }) {
  // live, the thought is written unfolded; it folds as soon as the reply starts
  const [open, setOpen] = useState(!!live)
  useEffect(() => { setOpen(!!live) }, [live])
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => { if (live && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight }, [live, text])
  const label = live ? "Thinking" : secs ? `Thought for ${fmtDur(secs)}` : "Thought"
  return (
    <div>
      <div className="flex min-h-7 min-w-0 items-center gap-1.5">
      {lead}
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={!text.trim() && !live}
        className="group/th -mx-1.5 inline-flex h-7 max-w-full items-center gap-0.5 rounded-full px-1.5 text-[13px] text-muted-foreground transition-colors enabled:hover:text-foreground">
        <Swap k={label} className="shrink-0">{live ? <Shimmer as="span" duration={1.5}>{label}</Shimmer> : <span>{label}</span>}</Swap>
        {summary && !LEAK_START.test(summary) && !open && <span className="ms-1.5 hidden min-w-0 truncate text-muted-foreground/70 italic sm:inline">— {summary}</span>}
        {text.trim() && <ChevronRight className={cn("size-3.5 shrink-0 transition-transform duration-200", open && "rotate-90")} />}
      </button>
      </div>
      <Reveal open={open && !!text.trim()}>
        <div ref={scroller} className="my-1 max-h-80 overflow-auto border-l border-neutral-900/10 py-0.5 pl-4 text-[13px]/[20.8px] whitespace-pre-wrap text-muted-foreground dark:border-neutral-100/12">
          {text.trim()}
        </div>
      </Reveal>
    </div>
  )
}

/* ---------------- tool pills ---------------- */

export type PillData = {
  id: string
  icon: "search" | "fetch" | "read"
  label: string        // "Searched the web"
  liveLabel: string    // "Searching the web"
  meta?: string        // "4 sources"
  running?: boolean
  sources?: Source[]
  detail?: string      // the query / the URL
  output?: string
}
const PILL_ICON = { search: Search, fetch: Globe, read: FileText }

/** Several searches in the same turn merge into one pill, like "Searched the web · 4 sources". */
export function ToolPills({ pills }: { pills: PillData[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const reduce = useReducedMotion()
  if (!pills.length) return null
  return (
    <div className="my-1.5">
      <div className="flex flex-wrap gap-1.5">
        {pills.map((p) => {
          const Icon = PILL_ICON[p.icon]
          const lbl = p.running ? p.liveLabel : p.label
          return (
            <motion.button key={p.id} type="button" onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id}
              initial={reduce ? false : { opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ type: "spring", stiffness: 500, damping: 40 }}
              className={cn("inline-flex h-[30px] max-w-full items-center gap-2 rounded-full border pr-3 pl-2.5 text-[13px] transition-colors",
                "border-neutral-900/10 bg-neutral-900/[0.035] hover:bg-neutral-900/[0.06] dark:border-[oklch(0.29_0_0)] dark:bg-[oklch(0.26_0_0)] dark:hover:bg-[oklch(0.29_0_0)]",
                open === p.id && "dark:bg-[oklch(0.29_0_0)]")}>
              <Icon className="size-3.5 shrink-0 text-muted-foreground" strokeWidth={1.8} />
              <Swap k={lbl}>{p.running ? <Shimmer as="span" duration={1.5}>{lbl}</Shimmer> : <span>{lbl}</span>}</Swap>
              {p.sources && p.sources.length > 0 && <SourceStack sources={p.sources} max={3} />}
              {p.meta && <span className="shrink-0 text-muted-foreground">{p.meta}</span>}
            </motion.button>
          )
        })}
      </div>
      {pills.map((p) => (
        <Reveal key={p.id} open={open === p.id}>
          <div className="mt-2 space-y-2 border-l border-neutral-900/10 pl-4 text-[13px] dark:border-neutral-100/12">
            {p.detail && <div className="text-muted-foreground">{p.detail}</div>}
            {p.sources && p.sources.length > 0 ? <SourcesList sources={p.sources} /> : p.output ? (
              <pre className="max-h-56 overflow-auto font-mono text-[11.5px]/[18px] whitespace-pre-wrap text-muted-foreground">{p.output}</pre>
            ) : null}
          </div>
        </Reveal>
      ))}
    </div>
  )
}

/** Builds a turn's web pills: all searches in one, one per page read. */
export function webPills(tools: { id: string; name: string; args: Record<string, unknown>; state: string; sources?: Source[]; output?: string }[]): PillData[] {
  const out: PillData[] = []
  const searches = tools.filter((t) => t.name === "web_search")
  if (searches.length) {
    const src = dedupe(searches.flatMap((t) => t.sources ?? []))
    const running = searches.some((t) => t.state === "running")
    out.push({ id: "search-" + searches[0].id, icon: "search", running,
      liveLabel: "Searching the web", label: "Searched the web",
      meta: src.length ? plural(src.length, "1 source", "# sources") : undefined, sources: src,
      detail: searches.map((t) => `"${String(t.args.query ?? "")}"`).join(" · "),
      output: src.length ? undefined : searches.map((t) => t.output ?? "").join("\n\n") })
  }
  for (const t of tools.filter((x) => x.name === "web_fetch")) {
    const u = String(t.args.url ?? "")
    out.push({ id: t.id, icon: "fetch", running: t.state === "running", liveLabel: `Reading ${host(u)}`, label: `Read ${host(u)}`,
      sources: u ? [{ url: u, title: t.sources?.[0]?.title }] : [], detail: u, output: t.output })
  }
  return out
}

/* ---------------- reply ---------------- */

/** Reply without a bubble. While streaming: per-word fade over 160 ms. */
export function Answer({ text, streaming, className }: { text: string; streaming?: boolean; className?: string }) {
  return (
    <div className={cn("text-[15px]/[24px] [overflow-wrap:anywhere] [&_p]:my-2.5 [&_li]:my-1", className)}>
      <MessageResponse isAnimating={!!streaming} animated={streaming ? { animation: "fadeIn", duration: 160, sep: "word" } : undefined}>
        {text}
      </MessageResponse>
    </div>
  )
}

/** Actions under a reply (30 px gray icons). */
export function AnswerActions({ text, onReply, onRetry }: { text: string; onReply?: () => void; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(false), 1400); return () => clearTimeout(t) }, [copied])
  const btn = "grid size-[30px] place-items-center rounded-[10px] text-muted-foreground transition-colors hover:bg-neutral-900/[0.05] hover:text-foreground dark:hover:bg-neutral-100/[0.06]"
  return (
    <div className="-ms-1.5 mt-1 flex items-center opacity-0 transition-opacity group-hover/turn:opacity-100 focus-within:opacity-100">
      <button type="button" aria-label="Copy" title="Copy" className={btn}
        onClick={() => { navigator.clipboard.writeText(text); setCopied(true); toast("Copied") }}>
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span key={copied ? "ok" : "cp"} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }} transition={{ duration: 0.14 }}>
            {copied ? <Check className="size-4" /> : <Copy className="size-4" strokeWidth={1.8} />}
          </motion.span>
        </AnimatePresence>
      </button>
      {onReply && <button type="button" aria-label="Reply" title="Reply (@mention)" className={btn} onClick={onReply}><CornerUpLeft className="size-4" strokeWidth={1.8} /></button>}
      {onRetry && <button type="button" aria-label="Retry" title="Make it speak again" className={btn} onClick={onRetry}><RotateCw className="size-4" strokeWidth={1.8} /></button>}
    </div>
  )
}
