/** Member logos: each one is recognized by its glyph and color, not by a bubble. */
import { cn } from "@/lib/utils"

export type Who = "chef" | "A" | "B"

export const AGENT_COLOR: Record<Who, string> = {
  chef: "text-zinc-500 dark:text-zinc-300",
  A: "text-violet-500 dark:text-violet-400",
  B: "text-emerald-500 dark:text-emerald-400",
}
export const AGENT_DOT: Record<Who, string> = { chef: "bg-zinc-400", A: "bg-violet-500", B: "bg-emerald-500" }

/** A's glyph: a four-pointed spark (assistant style). */
function SparkA({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <path d="M12 2c.6 4.8 2.2 6.4 7 7-4.8.6-6.4 2.2-7 7-.6-4.8-2.2-6.4-7-7 4.8-.6 6.4-2.2 7-7Z"
        fill="currentColor" />
    </svg>
  )
}
/** B's glyph: nested chevrons (executor / terminal style). */
function GlyphB({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 5l7 7-7 7M13 12h4" />
    </svg>
  )
}

/** A member's logo, in its color. The boss (human) keeps a badge with their initial. */
export function AgentMark({ who, label, size = 18, className }: { who: Who; label?: string; size?: number; className?: string }) {
  if (who === "chef") {
    return (
      <span className={cn("grid shrink-0 place-items-center rounded-full bg-zinc-200 font-semibold text-zinc-700 dark:bg-zinc-700 dark:text-zinc-100", className)}
        style={{ width: size, height: size, fontSize: size * 0.5 }}>
        {(label ?? "B").slice(0, 1).toUpperCase()}
      </span>
    )
  }
  const Glyph = who === "A" ? SparkA : GlyphB
  return <Glyph className={cn("shrink-0", AGENT_COLOR[who], className)} />
}
