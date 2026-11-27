import { motion } from "motion/react"
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message"
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning"
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "@/components/ai-elements/tool"
import { Shimmer } from "@/components/ai-elements/shimmer"
import { Badge } from "@/components/ui/badge"
import type { Msg } from "@/lib/api"

const words = (s: string) => s.trim().split(/\s+/).length

export const fadeUp = {
  initial: { opacity: 0, y: 6, filter: "blur(2px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] },
} as const

/** A transcript bubble (Inspect/Petri or chat), rendered with AI Elements. */
export function Bubble({ m, streaming, label }: { m: Msg; streaming?: boolean; label?: string }) {
  if (m.role === "tool")
    return (
      <motion.div {...fadeUp}>
        <Tool>
          <ToolHeader type="dynamic-tool" toolName={m.function || "tool"} title={`result · ${m.function || "tool"}`}
            state={m.error ? "output-error" : "output-available"} />
          <ToolContent>
            <ToolOutput output={m.text} errorText={m.error} />
          </ToolContent>
        </Tool>
      </motion.div>
    )

  const role = m.role === "user" ? "user" : m.role === "system" ? "system" : "assistant"
  const thinkingLive = streaming && !m.text
  return (
    <motion.div {...fadeUp}>
      <Message from={role === "user" ? "user" : "assistant"}>
        {role !== "user" && (
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label || m.role}
            {m.function ? ` · ${m.function}` : ""}
          </span>
        )}
        <MessageContent className={role === "system" ? "rounded-lg border border-dashed px-4 py-3 text-muted-foreground" : ""}>
          {(m.reasoning || thinkingLive) && (
            <Reasoning isStreaming={!!thinkingLive} defaultOpen={false}>
              <ReasoningTrigger
                getThinkingMessage={(s) =>
                  s ? <Shimmer duration={1.2}>Thinking…</Shimmer> : <span>Chain of thought · {words(m.reasoning || "")} words</span>
                }
              />
              <ReasoningContent>{m.reasoning || ""}</ReasoningContent>
            </Reasoning>
          )}
          {m.text && <MessageResponse isAnimating={streaming}>{m.text}</MessageResponse>}
          {m.error && <Badge variant="destructive">{m.error}</Badge>}
          {m.tool_calls?.map((t, i) => (
            <Tool key={i}>
              <ToolHeader type="dynamic-tool" toolName={t.function} state="output-available" title={t.function} />
              <ToolContent>
                <ToolInput input={t.arguments} />
              </ToolContent>
            </Tool>
          ))}
        </MessageContent>
      </Message>
    </motion.div>
  )
}
