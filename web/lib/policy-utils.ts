import type { Policy } from './journal-types'

export function isResourceMaterial(policy: Policy): boolean {
  return ['数据集目录', '用数需求', '授权运营披露'].includes(
    policy.content_kind || policy.instrument_type || '',
  )
}
