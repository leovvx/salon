/** Durée lisible : 0,4 s · 12 s · 2 min · 2 min 05 s · 1 h 03. */
export function fmtDur(secs?: number | null) {
  if (secs == null || !isFinite(secs) || secs < 0) return ""
  if (secs < 10) return `${(Math.round(secs * 10) / 10).toLocaleString("fr-CH")} s`
  if (secs < 60) return `${Math.round(secs)} s`
  const s = Math.round(secs)
  if (s < 3600) {
    const m = Math.floor(s / 60), r = s % 60
    return r ? `${m} min ${String(r).padStart(2, "0")} s` : `${m} min`
  }
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  return `${h} h ${String(m).padStart(2, "0")}`
}

/** Chrono façon horloge : 0:04 · 2:15 · 1:02:03. */
export function fmtClock(secs: number) {
  const s = Math.max(0, Math.floor(secs))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60
  const mm = h ? String(m).padStart(2, "0") : String(m)
  return `${h ? h + ":" : ""}${mm}:${String(r).padStart(2, "0")}`
}

export function host(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, "") } catch { return url }
}

export const favicon = (url: string) => `https://www.google.com/s2/favicons?domain=${host(url)}&sz=64`

export const plural = (n: number, one: string, many: string) => (n === 1 ? one : many.replace("#", String(n)))
