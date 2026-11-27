/**
 * Composer in the style of Arc UI's "AI composer" (measurements taken from the page, original code):
 * a rounded surface (r 20, border, p 10) with a 15/22.5 textarea that grows up to ~8 lines,
 * then a bar: "+", toggle pills (Web search, Deep thinking), and on the right the "model" chip
 * (here: who you are talking to, with their mark) that opens a menu with an effort row (here: autonomy),
 * and the send button: muted → arrow → stop square circled by the progress ring.
 */
import { forwardRef } from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { ArrowUp, Brain, Check, ChevronDown, Globe, Plus } from "lucide-react"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { AgentMark, type Who } from "./marks"

export type Target = { id: "all" | "A" | "B"; who: Who; name: string; note: string }
export type PlusItem = { label: string; icon: React.ReactNode; onSelect: () => void }
export type Suggestion = { label: string; icon: React.ReactNode; onSelect: () => void }

const morph = { type: "spring", stiffness: 520, damping: 34 } as const
const chipBase = "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border pr-3 pl-2.5 text-[13px] transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
const chipOff = "border-neutral-900/10 text-muted-foreground hover:bg-neutral-900/[0.04] hover:text-foreground dark:border-[oklch(0.29_0_0)] dark:hover:bg-[oklch(0.27_0_0)]"
const chipOn = "border-neutral-900/20 bg-neutral-900/[0.07] text-foreground dark:border-[oklch(0.38_0_0)] dark:bg-[oklch(0.31_0_0)]"
const menuSurface = "rounded-2xl border-neutral-900/10 p-1.5 dark:border-[oklch(0.29_0_0)] dark:bg-[oklch(0.22_0_0)]"

export const Composer = forwardRef<HTMLTextAreaElement, {
  value: string
  placeholder: string
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
  onClick?: (e: React.MouseEvent<HTMLTextAreaElement>) => void
  onBlur?: () => void
  running: boolean
  onSend: () => void
  onStop: () => void
  targets: Target[]
  to: Target["id"]
  setTo: (t: Target["id"]) => void
  web: boolean
  setWeb: (v: boolean) => void
  deep: boolean
  setDeep: (v: boolean) => void
  effort: number
  efforts: { label: string; value: number }[]
  setEffort: (n: number) => void
  plus: PlusItem[]
  overlay?: React.ReactNode
  suggestions?: Suggestion[]
}>(function Composer(p, ref) {
  const cur = p.targets.find((t) => t.id === p.to) ?? p.targets[0]
  const canSend = !!p.value.trim()
  const reduce = useReducedMotion()
  return (
    <div className="w-full">
      <div className={cn("relative rounded-[20px] border p-2.5 transition-colors",
        "border-neutral-900/12 bg-white shadow-[0_1px_2px_-1px_rgb(0_0_0/0.12)] focus-within:border-neutral-900/25",
        "dark:border-[oklch(0.29_0_0)] dark:bg-[oklch(0.24_0_0)] dark:shadow-none dark:focus-within:border-[oklch(0.36_0_0)]",
        p.to !== "all" && "border-amber-500/45 dark:border-amber-400/35 dark:focus-within:border-amber-400/55")}>
        {p.overlay}
        <textarea ref={ref} rows={1} value={p.value} onChange={p.onChange} onKeyDown={p.onKeyDown} onClick={p.onClick} onBlur={p.onBlur}
          aria-label="Message" placeholder={p.placeholder}
          className="block max-h-[196px] min-h-10 w-full resize-none bg-transparent px-2 pt-1 pb-2 text-[15px]/[22.5px] outline-none field-sizing-content placeholder:text-muted-foreground" />

        <div className="flex items-center gap-1.5">
          {/* + */}
          <DropdownMenu>
            <DropdownMenuTrigger aria-label="Add" className="grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors outline-none hover:bg-neutral-900/[0.05] hover:text-foreground data-[state=open]:bg-neutral-900/[0.05] dark:hover:bg-[oklch(0.28_0_0)] dark:data-[state=open]:bg-[oklch(0.28_0_0)]">
              <Plus className="size-[18px]" strokeWidth={1.8} />
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" sideOffset={8} className={cn(menuSurface, "min-w-56")}>
              {p.plus.map((it) => (
                <DropdownMenuItem key={it.label} onSelect={it.onSelect} className="gap-2.5 rounded-lg px-2.5 py-2 text-[13px]">
                  <span className="text-muted-foreground [&_svg]:size-4">{it.icon}</span>{it.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* toggles */}
          <button type="button" aria-pressed={p.web} onClick={() => p.setWeb(!p.web)} title={p.web ? "Agents can search the web" : "Web disabled for agents"}
            className={cn(chipBase, p.web ? chipOn : chipOff, "max-[560px]:w-8 max-[560px]:justify-center max-[560px]:px-0")}>
            <Globe className="size-4" strokeWidth={1.8} /><span className="max-[560px]:hidden">Web search</span>
          </button>
          <button type="button" aria-pressed={p.deep} onClick={() => p.setDeep(!p.deep)} title={p.deep ? "Thinking on every turn" : "Thinking only when useful"}
            className={cn(chipBase, p.deep ? chipOn : chipOff, "max-[560px]:w-8 max-[560px]:justify-center max-[560px]:px-0")}>
            <Brain className="size-4" strokeWidth={1.8} /><span className="max-[560px]:hidden">Deep thinking</span>
          </button>

          {/* "model" chip: who you are talking to */}
          <DropdownMenu>
            <DropdownMenuTrigger className="ms-auto inline-flex h-8 min-w-0 items-center gap-1.5 rounded-full pr-2 pl-2.5 text-[13px] outline-none transition-colors hover:bg-neutral-900/[0.05] data-[state=open]:bg-neutral-900/[0.05] dark:hover:bg-[oklch(0.28_0_0)] dark:data-[state=open]:bg-[oklch(0.28_0_0)]">
              <motion.span layout transition={reduce ? { duration: 0 } : morph} className="inline-flex min-w-0 items-center gap-1.5">
                <AgentMark who={cur.who} label={cur.name} size={16} className="size-4" />
                <span className="truncate font-medium text-foreground">{cur.name}</span>
                <span className="truncate text-muted-foreground max-[560px]:hidden">{cur.note}</span>
              </motion.span>
              <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="end" sideOffset={8} className={cn(menuSurface, "w-72")}>
              {p.targets.map((t) => (
                <DropdownMenuItem key={t.id} onSelect={() => p.setTo(t.id)} className="gap-3 rounded-xl px-2.5 py-2">
                  <AgentMark who={t.who} label={t.name} size={18} className="size-[18px]" />
                  <span className="min-w-0 flex-1 leading-tight">
                    <span className="block text-[14px] text-foreground">{t.name}</span>
                    <span className="block truncate text-[12px] text-muted-foreground">{t.note}</span>
                  </span>
                  {t.id === p.to && <Check className="size-4 text-foreground" />}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator className="my-1.5" />
              <div className="px-2.5 pt-1 pb-1.5">
                <div className="mb-2 flex items-center justify-between text-[13px]">
                  <span>Autonomy</span>
                  <span className="text-muted-foreground tabular-nums">{p.effort} turns without you</span>
                </div>
                <div className="flex rounded-xl border border-neutral-900/10 p-1 dark:border-[oklch(0.29_0_0)]">
                  {p.efforts.map((e) => (
                    <button key={e.value} type="button" onClick={() => p.setEffort(e.value)} aria-pressed={p.effort === e.value}
                      className={cn("relative h-8 flex-1 rounded-lg text-[13px] transition-colors", p.effort === e.value ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
                      {p.effort === e.value && <motion.span layoutId="effort-pill" transition={morph} className="absolute inset-0 rounded-lg bg-neutral-900/[0.07] dark:bg-[oklch(0.16_0_0)]" />}
                      <span className="relative">{e.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </DropdownMenuContent>
          </DropdownMenu>

          <SendButton running={p.running} canSend={canSend} onSend={p.onSend} onStop={p.onStop} />
        </div>
      </div>

      {p.suggestions && p.suggestions.length > 0 && (
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {p.suggestions.map((s, i) => (
            <motion.button key={s.label} type="button" onClick={s.onSelect}
              initial={reduce ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, delay: i * 0.04 }}
              className="inline-flex h-9 items-center gap-2 rounded-full border border-neutral-900/10 px-3.5 text-[13px] text-muted-foreground transition-colors hover:bg-neutral-900/[0.04] hover:text-foreground dark:border-[oklch(0.29_0_0)] dark:hover:bg-[oklch(0.24_0_0)] max-[400px]:w-full">
              <span className="[&_svg]:size-4">{s.icon}</span>{s.label}
            </motion.button>
          ))}
        </div>
      )}
    </div>
  )
})

/** Muted while empty → arrow → scaling stop square, circled by an arc that spins during the reply. */
function SendButton({ running, canSend, onSend, onStop }: { running: boolean; canSend: boolean; onSend: () => void; onStop: () => void }) {
  const reduce = useReducedMotion()
  return (
    <div className="relative grid size-8 shrink-0 place-items-center">
      <AnimatePresence>
        {running && (
          <motion.svg key="ring" viewBox="0 0 36 36" className="pointer-events-none absolute -inset-1 size-10 text-foreground" aria-hidden
            initial={{ opacity: 0 }} animate={{ opacity: 1, rotate: reduce ? 0 : 360 }} exit={{ opacity: 0 }}
            transition={{ opacity: { duration: 0.2 }, rotate: { duration: 1.1, repeat: Infinity, ease: "linear" } }}>
            <circle cx="18" cy="18" r="16.5" fill="none" stroke="currentColor" strokeOpacity={0.12} strokeWidth={1.5} />
            <circle cx="18" cy="18" r="16.5" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeDasharray="22 104" />
          </motion.svg>
        )}
      </AnimatePresence>
      <button type="button" onClick={running ? onStop : onSend} aria-disabled={!running && !canSend}
        aria-label={running ? "Stop" : canSend ? "Send message" : "Nothing to send"} title={running ? "Stop (Esc)" : "Send (Enter)"}
        className={cn("relative grid size-8 place-items-center overflow-hidden rounded-full transition-colors duration-150 outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
          running || canSend ? "bg-foreground text-background" : "bg-neutral-900/[0.07] text-muted-foreground dark:bg-[oklch(0.3_0_0)]")}>
        <AnimatePresence mode="popLayout" initial={false}>
          {running ? (
            <motion.span key="stop" aria-hidden className="size-2.5 rounded-[2.5px] bg-current"
              initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }} transition={morph} />
          ) : (
            <motion.span key="send" aria-hidden initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -14, opacity: 0 }} transition={morph}>
              <ArrowUp className="size-[17px]" strokeWidth={2} />
            </motion.span>
          )}
        </AnimatePresence>
      </button>
    </div>
  )
}
