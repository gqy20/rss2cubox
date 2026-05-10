import type { Row } from './types'

export function hasAiSummary(row: Pick<Row, 'core_event' | 'hidden_signal' | 'actionable' | 'reason'>): boolean {
  return Boolean(row.core_event || row.hidden_signal || row.actionable || row.reason)
}
