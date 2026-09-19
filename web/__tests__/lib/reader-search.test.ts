import { describe, it, expect } from 'vitest'
import {
  readerUrl,
  scopeForPath,
  activeFilterCount,
  buildContentSearch,
} from '../../lib/reader-search'
describe('reader search URLs', () => {
  it('keeps filters but resets pagination and selection for a new keyword', () => {
    const url = readerUrl(
      'signals',
      new URLSearchParams('mode=high&source=Example&page=4&id=old'),
      { search: '  Agent  ' },
    )
    expect(url).toBe('/signals?mode=high&source=Example&search=Agent')
  })
  it('clears only the search, preserving the selected filter', () => {
    expect(
      readerUrl(
        'signals',
        new URLSearchParams('search=AI&mode=high&id=old&page=2'),
        { search: '' },
      ),
    ).toBe('/signals?mode=high')
  })
  it('can select a record without losing the current result page', () => {
    expect(
      readerUrl(
        'policies',
        new URLSearchParams('search=AI&page=3'),
        { id: 'abc' },
        false,
      ),
    ).toBe('/policies?search=AI&page=3&id=abc')
  })
  it('does not count query or selection as extra filters', () => {
    expect(
      activeFilterCount(new URLSearchParams('search=AI&id=x&page=2&mode=all')),
    ).toBe(0)
    expect(
      activeFilterCount(
        new URLSearchParams('search=AI&mode=high&date=2026-09-19'),
      ),
    ).toBe(2)
  })
  it('uses the policy scope on a policy detail page', () =>
    expect(scopeForPath('/policies/abc')).toBe('policies'))
})
describe('content matching', () => {
  it('excludes internal ids, URLs, numeric scores and arbitrary metadata', () => {
    const match = buildContentSearch('jev', 'signals')!
    expect(match.where).toContain('title ILIKE $1')
    expect(match.where).toContain('full_text ILIKE $1')
    expect(match.where).not.toMatch(/\b(id|url|enrich_meta|importance_score)\b/)
    expect(match.order).toContain('WHEN title ILIKE $1 THEN 0')
    expect(match.select).toContain('AS search_excerpt')
  })
  it('treats SQL wildcard characters as literal input', () => {
    expect(buildContentSearch('100%_x', 'signals')?.values).toEqual([
      '%100\\%\\_x%',
      '100%_x',
    ])
  })
  it('searches policy provisions and full text as well as the title', () => {
    const match = buildContentSearch('申报', 'policies')!
    expect(match.where).toContain('key_provisions::text ILIKE $1')
    expect(match.where).toContain('full_text ILIKE $1')
  })
  it('does not add relevance sorting to an unfiltered list', () =>
    expect(buildContentSearch('', 'signals')).toBeNull())
})
