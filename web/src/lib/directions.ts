export const DIRECTIONS = { chaos_first: 'Chaos → item → Divines', divine_first: 'Divines → item → Chaos' } as const
export type Direction = keyof typeof DIRECTIONS
