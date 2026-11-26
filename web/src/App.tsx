import { useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ChatView } from "@/views/chat"
import { RoomView } from "@/views/room"
import { cn } from "@/lib/utils"

const TABS = [
  { id: "room", label: "Salon" },
  { id: "chat", label: "Chat" },
] as const
type Tab = (typeof TABS)[number]["id"]

export default function App() {
  const [tab, setTab] = useState<Tab>("room")

  return (
    <TooltipProvider>
      <header className="sticky top-0 z-20 flex h-14 items-center gap-6 border-b bg-background/70 px-6 backdrop-blur-xl">
        <span className="text-sm font-semibold tracking-tight">
          Salon<span className="text-muted-foreground"> · Ateliers</span>
        </span>
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={cn("relative rounded-md px-3 py-1.5 text-sm transition-colors", tab === t.id ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
              {tab === t.id && (
                <motion.span layoutId="tab" className="absolute inset-0 rounded-md bg-muted" transition={{ type: "spring", bounce: 0.2, duration: 0.45 }} />
              )}
              <span className="relative">{t.label}</span>
            </button>
          ))}
        </nav>
      </header>
      <AnimatePresence mode="wait" initial={false}>
        <motion.main key={tab} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18, ease: "easeOut" }}>
          {tab === "room" && <RoomView />}
          {tab === "chat" && <ChatView />}
        </motion.main>
      </AnimatePresence>
      <Toaster position="bottom-center" />
    </TooltipProvider>
  )
}
