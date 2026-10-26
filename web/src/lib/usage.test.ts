import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { pageOf, trackFeature, trackPage } from './usage'

describe('usage beacons', () => {
  const beacon = vi.fn(() => true)
  beforeEach(() => {
    beacon.mockClear()
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true })
    Object.defineProperty(navigator, 'doNotTrack', { value: null, configurable: true })
  })
  afterEach(() => {
    Object.defineProperty(navigator, 'globalPrivacyControl', { value: undefined, configurable: true })
  })

  it('names only known pages', () => {
    expect(pageOf('/')).toBe('/')
    expect(pageOf('/price-check/')).toBe('/price-check')
    expect(pageOf('/some/thing')).toBe('/not-found')
  })

  it('sends the page and counts a feature once per page view', () => {
    trackPage('/launch')
    trackFeature('launch-pick')
    trackFeature('launch-pick')
    expect(beacon.mock.calls.map((c) => (c as unknown[])[0])).toEqual([
      '/api/hit?e=page%3A%2Flaunch',
      '/api/hit?e=feature%3Alaunch-pick',
    ])
    trackPage('/launch')
    trackFeature('launch-pick')
    expect(beacon).toHaveBeenCalledTimes(4)
  })

  it("doesn't count the admin page", () => {
    trackPage('/admin')
    expect(beacon).not.toHaveBeenCalled()
  })

  it('sends nothing with Do-Not-Track or Global Privacy Control', () => {
    Object.defineProperty(navigator, 'doNotTrack', { value: '1', configurable: true })
    trackPage('/')
    Object.defineProperty(navigator, 'doNotTrack', { value: null, configurable: true })
    Object.defineProperty(navigator, 'globalPrivacyControl', { value: true, configurable: true })
    trackPage('/')
    expect(beacon).not.toHaveBeenCalled()
  })
})
