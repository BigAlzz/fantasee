import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import Home from '@/app/page'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock the TanStack Query hook
vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual('@tanstack/react-query')
  return {
    ...actual,
    useQuery: () => ({
      data: [],
      isLoading: false,
    }),
    useMutation: () => ({
      mutate: vi.fn(),
      isPending: false,
    }),
  }
})

describe('Home Page', () => {
  const queryClient = new QueryClient()

  it('renders the library header', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Home />
      </QueryClientProvider>
    )
    
    expect(screen.getByText(/Your Library/i)).toBeInTheDocument()
    expect(screen.getByText(/FANTASEE/i)).toBeInTheDocument()
  })

  it('shows empty library message when no stories exist', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Home />
      </QueryClientProvider>
    )
    
    expect(screen.getByText(/No stories yet/i)).toBeInTheDocument()
  })
})
