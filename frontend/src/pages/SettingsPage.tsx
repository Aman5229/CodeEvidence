import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Eye, EyeOff, KeyRound, Moon, Server, Sun, XCircle } from 'lucide-react'
import { useState } from 'react'
import { getApiKey, setApiKey } from '../api/apiKey'
import { API_URL } from '../api/client'
import { useReadiness } from '../api/hooks'
import { useToast } from '../components/ui/toast'
import { switchTheme, useTheme } from '../lib/theme'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const readiness = useReadiness()
  const [key, setKey] = useState(getApiKey())
  const [visible, setVisible] = useState(false)
  const [saved, setSaved] = useState(false)
  const theme = useTheme()
  const toast = useToast()

  function save(event: React.FormEvent) {
    event.preventDefault()
    setApiKey(key.trim())
    setSaved(true)
    queryClient.invalidateQueries() // refetch everything with the new key
    toast({ title: key.trim() ? 'API key saved' : 'API key removed', description: 'Data is being reloaded with it.' })
  }
  const checks = readiness.data?.checks?.checks ?? {}

  return (
    <div className="stack lg" style={{ maxWidth: 760 }}>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Connection to the CodeEvidence API, and how the dashboard looks.</p>
        </div>
      </div>

      <section className="card" aria-labelledby="key-title">
        <div className="card-header"><h2 id="key-title" className="row"><KeyRound size={15} aria-hidden="true" /> API key</h2></div>
        <form className="card-body stack" onSubmit={save}>
          <p className="muted" style={{ margin: 0 }}>
            Create one with <code>docker compose exec app python -m scripts.create_api_key "dashboard"</code>. It is stored in this browser only.
          </p>
          <div className="row">
            <input
              id="api-key"
              className="input grow"
              type={visible ? 'text' : 'password'}
              autoComplete="off"
              placeholder="ce_…"
              aria-label="API key"
              value={key}
              onChange={(event) => {
                setKey(event.target.value)
                setSaved(false)
              }}
            />
            <button type="button" className="btn ghost" onClick={() => setVisible(!visible)} aria-label={visible ? 'Hide key' : 'Show key'}>
              {visible ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
            <button type="submit" className="btn primary">{saved ? 'Saved' : 'Save'}</button>
          </div>
        </form>
      </section>

      <section className="card" aria-labelledby="api-title">
        <div className="card-header">
          <h2 id="api-title" className="row"><Server size={15} aria-hidden="true" /> API</h2>
          <code className="muted">{API_URL}</code>
        </div>
        <div className="card-body stack" style={{ gap: 8 }}>
          {readiness.isPending && <span className="muted">Checking…</span>}
          {readiness.isError && <span style={{ color: 'var(--high)' }}>The API cannot be reached at {API_URL}.</span>}
          {Object.entries(checks).map(([name, result]) => (
            <div key={name} className="row">
              {result === 'ok' ? <CheckCircle2 size={15} color="var(--low)" aria-hidden="true" /> : <XCircle size={15} color="var(--high)" aria-hidden="true" />}
              <span className="grow" style={{ textTransform: 'capitalize' }}>{name}</span>
              <span className={result === 'ok' ? 'muted' : ''} style={result === 'ok' ? undefined : { color: 'var(--high)' }}>{result}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="theme-title">
        <div className="card-header"><h2 id="theme-title">Appearance</h2></div>
        <div className="card-body row">
          {(['dark', 'light'] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={`btn${theme === value ? ' active' : ''}`}
              aria-pressed={theme === value}
              onClick={(event) => switchTheme(value, { x: event.clientX, y: event.clientY })}
            >
              {value === 'dark' ? <Moon size={14} aria-hidden="true" /> : <Sun size={14} aria-hidden="true" />} {value}
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}
