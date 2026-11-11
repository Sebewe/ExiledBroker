import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import Crafting from './Crafting'

const renderPage = (search = '') =>
  render(
    <MemoryRouter initialEntries={[`/crafting${search}`]}>
      <Crafting />
    </MemoryRouter>,
  )

describe('Crafting', () => {
  it('recommends a route for the default mods and lists every method', () => {
    renderPage()
    expect(screen.getByText('Best route')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Buy a base with Vicious Bite fractured/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Plain base, no fracturing/ })).toBeTruthy()
  })

  it('asks for a mod when none is picked', () => {
    renderPage('?mod=none')
    expect(screen.getByText('Pick at least one mod.')).toBeTruthy()
    expect(screen.queryByText('Best route')).toBeNull()
  })

  it('blocks a third prefix', () => {
    renderPage('?mod=feasting_fiends&mod=renewal')
    const third = screen.getByRole('button', { name: /Rotten Claws/ }) as HTMLButtonElement
    expect(third.disabled).toBe(true)
    expect(third.title).toBe('A jewel has at most 2 prefixes.')
  })

  it('shows the steps of the method you pick', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Buy a base with Feasting Fiends fractured/ }))
    expect(screen.getByText(/Buy a Large Cluster Jewel with Feasting Fiends fractured/)).toBeTruthy()
  })
})
