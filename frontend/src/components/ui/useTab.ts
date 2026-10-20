import { useSearchParams } from 'react-router'
import type { TabSpec } from './Tabs'

/** The active tab, kept in the URL (?tab=files) so it survives a reload and can be shared. */
export function useTab(tabs: TabSpec[], fallback: string = tabs[0].id): [string, (id: string) => void] {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const active = tabs.some((tab) => tab.id === requested) ? (requested as string) : fallback
  const select = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('tab', id)
    setParams(next, { replace: true })
  }
  return [active, select]
}
