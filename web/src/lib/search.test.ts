import { describe, expect, it } from 'vitest'
import { matchOptions } from './search'

const options = [
  { id: 'a', name: 'Greater Chaos Orb', group: 'Currency' },
  { id: 'b', name: 'Chaos Orb', group: 'Currency' },
  { id: 'c', name: 'Deafening Essence of Greed', group: 'Essence' },
  { id: 'd', name: 'Splinter of Chayula', group: 'Breach' },
]
const ids = (q: string) => matchOptions(options, q).map((o) => o.id)

describe('matchOptions', () => {
  it('keeps the given order when nothing is typed', () => {
    expect(ids('')).toEqual(['a', 'b', 'c', 'd'])
    expect(ids('   ')).toEqual(['a', 'b', 'c', 'd'])
  })
  it('matches every word anywhere in the name or group, ignoring case', () => {
    expect(ids('ORB grea')).toEqual(['a'])
    expect(ids('essence')).toEqual(['c'])
    expect(ids('breach')).toEqual(['d'])
    expect(ids('mirror')).toEqual([])
  })
  it('puts names that start with the text first', () => {
    expect(ids('chaos')).toEqual(['b', 'a'])
    expect(ids('cha')).toEqual(['b', 'a', 'd'])
  })
})
