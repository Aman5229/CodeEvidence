import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnimatedNumber } from '../motion/AnimatedNumber'
import { Donut, Funnel, Gauge, ScoreRing } from './Charts'

describe('charts', () => {
  it('donut shows the total and every slice in its legend', () => {
    render(
      <Donut
        centerLabel="scored PRs"
        slices={[
          { label: 'High', value: 13, color: 'red' },
          { label: 'Medium', value: 39, color: 'orange' },
          { label: 'Low', value: 349, color: 'green' },
        ]}
      />,
    )

    expect(screen.getByRole('img', { name: 'scored PRs: 401' })).toBeInTheDocument()
    expect(screen.getByText('87%')).toBeInTheDocument() // 349 of 401
    expect(screen.getAllByText('349').length).toBeGreaterThan(0)
  })

  it('gauge and ring describe the score for screen readers', () => {
    render(
      <>
        <Gauge score={72} level="high" />
        <ScoreRing score={12} level="low" />
      </>,
    )

    expect(screen.getByRole('img', { name: 'Risk score 72 of 100, high' })).toHaveTextContent('72')
    expect(screen.getByRole('img', { name: 'Risk 12 of 100, low' })).toHaveTextContent('12')
  })

  it('funnel lists each stage with its value', () => {
    render(
      <Funnel
        stages={[
          { label: 'Proposed by the model', value: 20, color: 'blue' },
          { label: 'Passed verification', value: 12, color: 'green' },
        ]}
      />,
    )

    expect(screen.getByText('Proposed by the model')).toBeInTheDocument()
    expect(screen.getAllByText('12').length).toBeGreaterThan(0)
  })

  it('animated numbers end on the formatted value', () => {
    render(
      <p>
        <AnimatedNumber value={100407} /> · <AnimatedNumber value={0.425} format="percent" /> · <AnimatedNumber value={0.0042} format="usd" />
      </p>,
    )

    expect(screen.getAllByText('100,407').length).toBeGreaterThan(0)
    expect(screen.getAllByText('43%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$0.0042').length).toBeGreaterThan(0)
  })
})
