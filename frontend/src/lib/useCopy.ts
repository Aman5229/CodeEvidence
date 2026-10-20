import { useState } from 'react'

/** Copy text to the clipboard; `copied` is true for a moment afterwards. */
export function useCopy(): [boolean, (text: string) => Promise<void>] {
  const [copied, setCopied] = useState(false)
  const copy = async (text: string) => {
    if (!navigator.clipboard) return
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }
  return [copied, copy]
}
