import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router'
import { describe, expect, it } from 'vitest'
import { renderAt } from '../../test/render'
import { TabBar } from './Tabs'
import { useTab } from './useTab'

const TABS = [
  { id: 'one', label: 'One' },
  { id: 'two', label: 'Two', count: 3 },
  { id: 'three', label: 'Three' },
]

function Harness() {
  const [active, select] = useTab(TABS)
  const location = useLocation()
  return (
    <>
      <TabBar tabs={TABS} active={active} onSelect={select} label="Sections" />
      <p>active: {active}</p>
      <p>url: {location.search}</p>
    </>
  )
}

describe('tabs', () => {
  it('reads the tab from the URL and writes it back', async () => {
    renderAt('/page?tab=two', '/page', <Harness />)
    expect(screen.getByRole('tab', { name: /Two/ })).toHaveAttribute('aria-selected', 'true')

    await userEvent.click(screen.getByRole('tab', { name: 'Three' }))

    expect(screen.getByText('active: three')).toBeInTheDocument()
    expect(screen.getByText('url: ?tab=three')).toBeInTheDocument()
  })

  it('moves with the arrow keys and ignores unknown tabs', async () => {
    renderAt('/page?tab=nope', '/page', <Harness />)
    expect(screen.getByText('active: one')).toBeInTheDocument()

    screen.getByRole('tab', { name: 'One' }).focus()
    await userEvent.keyboard('{ArrowLeft}')

    expect(screen.getByText('active: three')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Three' })).toHaveFocus()
  })
})
