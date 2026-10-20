import { describe, expect, it } from 'vitest'
import { formatDuration, formatPercent, formatUsd, share, timeAgo } from './format'

describe('format', () => {
  it('says how long ago', () => {
    const now = new Date('2026-10-19T12:00:00Z')
    expect(timeAgo('2026-10-19T11:59:30Z', now)).toBe('just now')
    expect(timeAgo('2026-10-19T09:00:00Z', now)).toBe('3 hours ago')
    expect(timeAgo('2026-10-18T12:00:00Z', now)).toBe('yesterday')
  })

  it('formats money, shares and durations', () => {
    expect(formatUsd(0)).toBe('$0')
    expect(formatUsd(0.0042)).toBe('$0.0042')
    expect(formatUsd(1.5)).toBe('$1.50')
    expect(formatPercent(0.425)).toBe('43%')
    expect(formatPercent(null)).toBe('—')
    expect(formatDuration(850)).toBe('850 ms')
    expect(formatDuration(18602)).toBe('18.6 s')
    expect(share(1, 0)).toBe(0)
  })
})
