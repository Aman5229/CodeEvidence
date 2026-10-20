import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { useToast } from './toast'
import { ToastProvider } from './Toaster'

function Trigger() {
  const toast = useToast()
  return (
    <button type="button" onClick={() => toast({ title: 'Feedback saved', description: 'Marked as useful.' })}>
      Save
    </button>
  )
}

describe('toasts', () => {
  it('appear in a live region and can be dismissed', async () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('status')).toHaveTextContent('Feedback saved')

    await act(() => userEvent.click(screen.getByRole('button', { name: 'Dismiss' })))
    // The toast leaves through an exit animation: wait for it to be removed
    await waitFor(() => expect(screen.getByRole('status')).not.toHaveTextContent('Feedback saved'))
  })
})
