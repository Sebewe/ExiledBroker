import { useParam } from './useParam'

/** The chosen league (URL `league`), defaulting to the first offered (the newest). */
export function useLeague(names: string[]) {
  const [chosen, setChosen] = useParam<string>('league', '')
  const league = names.includes(chosen) ? chosen : names[0]
  return [league, setChosen] as const
}
