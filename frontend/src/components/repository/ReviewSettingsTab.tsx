import { Ban, BookOpen, FileCog, GitPullRequestDraft, Route, ShieldCheck, Wrench } from 'lucide-react'
import { motion } from 'motion/react'
import { useRepositoryConfig } from '../../api/hooks'
import { item, list } from '../../lib/motion'
import { ErrorMessage, Loading } from '../ui/States'

const EXAMPLE = `profile: chill            # chill: fewer comments, no low-severity nits; assertive: more
exclude:                  # never reviewed
  - "docs/**"
  - "**/*.generated.ts"
instructions:             # extra rules for matching files
  - path: "src/api/**"
    text: "Every endpoint must check the API key and validate its input."
guidelines: true          # read CLAUDE.md, AGENTS.md, .cursorrules, CONTRIBUTING.md...
tools:                    # static analysis on the changed lines
  ruff: true
  semgrep: true
  gitleaks: true
merge_check:
  block_on: high          # the commit status fails on: high, medium, never`

const BLOCK_ON: Record<string, string> = {
  high: 'fails when a high-severity finding is shown',
  medium: 'fails when a medium or high-severity finding is shown',
  never: 'always passes (informational)',
}

/** The review settings in .codeevidence.yaml on the default branch, read live from GitHub. */
export function ReviewSettingsTab({ repositoryId, defaultBranch }: { repositoryId: number; defaultBranch: string | undefined }) {
  const config = useRepositoryConfig(repositoryId)
  if (config.isPending) return <Loading what="the review settings" />
  if (config.isError) return <ErrorMessage error={config.error} />
  const data = config.data

  return (
    <motion.div className="stack lg" variants={list} initial="hidden" animate="show">
      <motion.div variants={item} className={`alert ${data.error ? 'warn' : 'info'} small`}>
        <FileCog size={15} aria-hidden="true" />
        <div>
          {data.source === 'file'
            ? <>Read from <code>.codeevidence.yaml</code> on <code>{defaultBranch ?? 'the default branch'}</code>. A PR cannot change the rules it is reviewed by.</>
            : <>No <code>.codeevidence.yaml</code> on <code>{defaultBranch ?? 'the default branch'}</code>: reviews use the defaults below.</>}
          {data.error && <><br /><strong>The file was not used:</strong> {data.error}</>}
        </div>
      </motion.div>
      <motion.div variants={item} className="grid two">
        <section className="card card-body stack" style={{ gap: 10 }} aria-label="Review style">
          <h2 className="row"><GitPullRequestDraft size={15} aria-hidden="true" /> Review style</h2>
          <div className="row"><span className="grow">Profile</span><span className="badge accent">{data.profile}</span></div>
          <p className="muted small" style={{ margin: 0 }}>
            {data.profile === 'chill'
              ? 'Fewer comments: low-severity findings are left out unless a rule or tool backs them.'
              : 'More comments, low severity included.'}
          </p>
          <div className="row"><span className="grow row"><ShieldCheck size={14} aria-hidden="true" /> Merge check</span><span className="badge outline">{data.merge_check.block_on}</span></div>
          <p className="muted small" style={{ margin: 0 }}>The commit status <code>codeevidence/review</code> {BLOCK_ON[data.merge_check.block_on]}.</p>
        </section>
        <section className="card card-body stack" style={{ gap: 10 }} aria-label="Static analysis">
          <h2 className="row"><Wrench size={15} aria-hidden="true" /> Static analysis</h2>
          {(['ruff', 'semgrep', 'gitleaks'] as const).map((tool) => (
            <div key={tool} className="row">
              <code className="grow">{tool}</code>
              <span className={`badge ${data.tools[tool] ? 'low' : 'outline'}`}>{data.tools[tool] ? 'on' : 'off'}</span>
            </div>
          ))}
          <p className="muted small" style={{ margin: 0 }}>Their findings on added lines become signals the reviewer can cite.</p>
        </section>
        <section className="card card-body stack" style={{ gap: 10 }} aria-label="Excluded files">
          <h2 className="row"><Ban size={15} aria-hidden="true" /> Never reviewed</h2>
          {data.exclude.length === 0 ? <span className="muted small">Nothing excluded (lock files, vendored and generated code are always skipped).</span> : (
            <div className="row wrap">{data.exclude.map((pattern) => <code key={pattern} className="badge outline">{pattern}</code>)}</div>
          )}
        </section>
        <section className="card card-body stack" style={{ gap: 10 }} aria-label="Guidelines">
          <h2 className="row"><BookOpen size={15} aria-hidden="true" /> Guidelines</h2>
          {!data.guidelines ? <span className="muted small">Turned off.</span> : data.guideline_files.length === 0 ? (
            <span className="muted small">None found (CLAUDE.md, AGENTS.md, .cursorrules, .github/copilot-instructions.md, CONTRIBUTING.md at the root or in .github/).</span>
          ) : (
            <div className="row wrap">{data.guideline_files.map((name) => <code key={name} className="badge outline">{name}</code>)}</div>
          )}
        </section>
      </motion.div>
      <motion.section variants={item} className="card" aria-label="Path instructions">
        <div className="card-header"><h2 className="row"><Route size={15} aria-hidden="true" /> Path instructions</h2></div>
        <div className="card-body stack" style={{ gap: 8 }}>
          {data.instructions.length === 0 && <span className="muted small">None: add `instructions` to give the reviewer rules for some paths.</span>}
          {data.instructions.map((instruction) => (
            <div key={`${instruction.path}:${instruction.text}`} className="row" style={{ alignItems: 'flex-start' }}>
              <code className="badge outline">{instruction.path}</code>
              <span>{instruction.text}</span>
            </div>
          ))}
        </div>
      </motion.section>
      <motion.details variants={item} className="evidence-item">
        <summary>Example <code>.codeevidence.yaml</code>, with every setting</summary>
        <pre>{EXAMPLE}</pre>
      </motion.details>
    </motion.div>
  )
}
