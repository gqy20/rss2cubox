'use client'

import Link from 'next/link'
import type { Dispatch, ReactNode, RefObject, SetStateAction } from 'react'
import { memo } from 'react'
import { AlertCircle, Brain, CalendarDays, Check, Copy, Download, Search, ChevronRight, ChevronDown, X, Inbox } from 'lucide-react'
import MarkdownRenderer from './MarkdownRenderer'
import FeedCard from './FeedCard'
import type { Metrics, Row, InsightKey } from './types'
import { AnimatedNumber, formatGroupTitle, Logo } from './utils'
import { Button, MenuPanel, PopoverMenu } from './ui'
import type { InsightHistoryItem } from '../lib/signalStore'

export type ParsedInsightItem = {
  title: string
  content?: string
  sourceUrls?: string[]
  sourceTitles?: string[]
}

export type InsightPanel = {
  key: InsightKey
  title: string
  icon: ReactNode
  items: ParsedInsightItem[]
}

export type KpiItem = {
  key: string
  title: string
  value: number
  tone: string
  delta: { text: string; trend: 'up' | 'down' | 'flat' } | null
  onClick: () => void
}

export type FeedGroupView = {
  id: string
  title: string
  items: Row[]
  total: number
  loaded: boolean
}

export type GroupState = {
  loading: boolean
  loaded: boolean
  items: Row[]
  hasMore: boolean
}

type DashboardLeftProps = {
  generatedAt?: string
  kpis: readonly KpiItem[]
  activeInsightPanel?: InsightPanel
  visibleInsightPanels: InsightPanel[]
  onSelectInsightKey: (key: InsightKey) => void
  onCopyInsight: (title: string, items: ParsedInsightItem[]) => void
  onExport: () => void
  chartsTriggerRef: RefObject<HTMLDivElement | null>
  shouldLoadCharts: boolean
  onLoadCharts: () => void
  chartsNode: ReactNode
  actionMessage: { type: 'success' | 'error'; text: string } | null
}

export function DashboardLeft({
  generatedAt,
  kpis,
  activeInsightPanel,
  visibleInsightPanels,
  onSelectInsightKey,
  onCopyInsight,
  onExport,
  chartsTriggerRef,
  shouldLoadCharts,
  onLoadCharts,
  chartsNode,
  actionMessage,
}: DashboardLeftProps) {
  return (
    <div className="dashboard-left">
      <DashboardHeader generatedAt={generatedAt} onExport={onExport} />
      <KpiGrid items={kpis} />
      {activeInsightPanel && (
        <InsightBriefing
          activePanel={activeInsightPanel}
          visiblePanels={visibleInsightPanels}
          onSelectInsightKey={onSelectInsightKey}
          onCopy={onCopyInsight}
        />
      )}
      <div ref={chartsTriggerRef}>
        {shouldLoadCharts ? chartsNode : <DeferredCharts onLoad={onLoadCharts} />}
      </div>
      {actionMessage && <ActionMessage message={actionMessage} />}
    </div>
  )
}

type DashboardHeaderProps = {
  generatedAt?: string
  onExport: () => void
}

function DashboardHeader({ generatedAt, onExport }: DashboardHeaderProps) {
  return (
    <div className="header-container dashboard-header">
      <div>
        <div className="dashboard-brand">
          <Logo size={40} />
          <h1 className="h1">RSS 信号控制台</h1>
        </div>
        <div className="muted dashboard-updated">
          <span suppressHydrationWarning>最后更新：{generatedAt}</span>
        </div>
      </div>
      <div className="dashboard-header-actions">
        <Link href="/predictions" className="predictions-nav-link">
          <Brain size={13} /> 预测循环
        </Link>
        <Button onClick={onExport}>
          <Download size={13} /> 导出 JSON
        </Button>
      </div>
    </div>
  )
}

const KpiGrid = memo(function KpiGrid({ items }: { items: readonly KpiItem[] }) {
  return (
    <section className="kpi">
      {items.map((item) => (
        <button key={item.key} className="glass kpi-card" onClick={item.onClick}>
          <div className="kpi-title">{item.title}</div>
          <div className="kpi-value" style={{ color: item.tone }}>
            <AnimatedNumber value={item.value} />
          </div>
          {item.delta && <div className={`kpi-delta ${item.delta.trend}`}>{item.delta.text}</div>}
        </button>
      ))}
    </section>
  )
})

type InsightBriefingProps = {
  activePanel: InsightPanel
  visiblePanels: InsightPanel[]
  onSelectInsightKey: (key: InsightKey) => void
  onCopy: (title: string, items: ParsedInsightItem[]) => void
}

const InsightBriefing = memo(function InsightBriefing({ activePanel, visiblePanels, onSelectInsightKey, onCopy }: InsightBriefingProps) {
  return (
    <section className="glass briefing-panel">
      <div className="briefing-head">
        <div className="briefing-title-row">
          <h2 className="briefing-title">{activePanel.title}</h2>
          <div className="briefing-tabs" role="tablist" aria-label="洞察类别">
            {visiblePanels
              .filter((panel) => panel.key !== activePanel.key)
              .map((panel) => (
                <button
                  key={panel.key}
                  role="tab"
                  aria-selected={false}
                  className="briefing-tab"
                  onClick={() => onSelectInsightKey(panel.key)}
                >
                  {panel.icon}
                  <span>{panel.title}</span>
                </button>
              ))}
          </div>
        </div>
        <Button iconOnly onClick={() => onCopy(activePanel.title, activePanel.items)} title="复制" aria-label="复制">
          <Copy size={14} />
        </Button>
      </div>
      <ol className="briefing-list custom-scrollbar">
        {activePanel.items.slice(0, 5).map((item, i) => (
          <li key={`${activePanel.key}-${i}-${item.title}`}>
            <span className="briefing-index">{String(i + 1).padStart(2, '0')}</span>
            <div>
              <div className="briefing-item-title"><MarkdownRenderer inline>{item.title}</MarkdownRenderer></div>
              {item.content && <div className="briefing-item-content"><MarkdownRenderer inline>{item.content}</MarkdownRenderer></div>}
              {item.sourceUrls && item.sourceUrls.length > 0 && (
                <div className="briefing-sources">
                  {item.sourceUrls.map((url, j) => (
                    <a
                      key={j}
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="briefing-source-link"
                      title={item.sourceTitles?.[j] || url}
                    >
                      {item.sourceTitles?.[j] || new URL(url).hostname.replace('www.', '')}
                    </a>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
})

const DeferredCharts = memo(function DeferredCharts({ onLoad }: { onLoad: () => void }) {
  return (
    <section className="charts-grid charts-section-spaced">
      <div className="glass chart-card chart-deferred-card">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-text skeleton-text-short" />
        <div className="skeleton skeleton-chart" />
        <Button onClick={onLoad} style={{ marginTop: 12 }}>加载图表</Button>
      </div>
      <div className="glass chart-card chart-deferred-card">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-text skeleton-text-short" />
        <div className="skeleton skeleton-chart" />
        <Button onClick={onLoad} style={{ marginTop: 12 }}>加载图表</Button>
      </div>
    </section>
  )
})

const ActionMessage = memo(function ActionMessage({ message }: { message: { type: 'success' | 'error'; text: string } }) {
  return (
    <div className={`action-message ${message.type === 'success' ? 'success' : 'error'}`} role="status">
      {message.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
      <span>{message.text}</span>
    </div>
  )
})

type DashboardRightProps = {
  search: string
  searchRef: RefObject<HTMLInputElement | null>
  onSearchChange: (value: string) => void
  filter: 'all' | 'analyzed' | 'high_value'
  onFilterChange: (filter: 'all' | 'analyzed' | 'high_value') => void
  selectedDateKey: string | null
  todayKey: string
  yesterdayKey: string
  dateMenuOpen: boolean
  onDateMenuOpenChange: (open: boolean) => void
  dateQuery: string
  onDateQueryChange: (value: string) => void
  filteredDateOptions: string[]
  metrics: Metrics
  selectedSource: string | null
  selectedTag: string | null
  onClearSource: () => void
  onClearTag: () => void
  onClearAll: () => void
  onToggleToday: () => void
  onJumpToDate: (dayKey: string) => void
  onExport: () => void
  displayedRows: Row[]
  isSearchMode: boolean
  searchTotal: number
  hasLoadingGroup: boolean
  groupedRows: FeedGroupView[]
  groupData: Record<string, GroupState>
  collapsedGroups: Record<string, boolean>
  setCollapsedGroups: Dispatch<SetStateAction<Record<string, boolean>>>
  loadGroupData: (dayKey: string) => Promise<void>
  timelineRef: RefObject<HTMLDivElement | null>
  loadMoreRef: RefObject<HTMLDivElement | null>
  groupRefs: RefObject<Record<string, HTMLDivElement | null>>
  now: Date | null
  hoveredRowKey: string | null
  onHoverEnter: (key: string) => void
  onHoverLeave: (key: string) => void
  onToggleOpen: (key: string) => void
  onTagClick: (tag: string) => void
  searchLoading: boolean
  loadingMore: boolean
}

export function DashboardRight({
  search,
  searchRef,
  onSearchChange,
  filter,
  onFilterChange,
  selectedDateKey,
  todayKey,
  yesterdayKey,
  dateMenuOpen,
  onDateMenuOpenChange,
  dateQuery,
  onDateQueryChange,
  filteredDateOptions,
  metrics,
  selectedSource,
  selectedTag,
  onClearSource,
  onClearTag,
  onClearAll,
  onToggleToday,
  onJumpToDate,
  onExport,
  displayedRows,
  isSearchMode,
  searchTotal,
  hasLoadingGroup,
  groupedRows,
  groupData,
  collapsedGroups,
  setCollapsedGroups,
  loadGroupData,
  timelineRef,
  loadMoreRef,
  groupRefs,
  now,
  hoveredRowKey,
  onHoverEnter,
  onHoverLeave,
  onToggleOpen,
  onTagClick,
  searchLoading,
  loadingMore,
}: DashboardRightProps) {
  const resultCount = isSearchMode
    ? displayedRows.length
    : selectedDateKey
      ? metrics.daily_totals?.[selectedDateKey] ?? displayedRows.length
      : selectedSource || selectedTag || filter !== 'all'
        ? displayedRows.length
        : Object.values(metrics.daily_totals || {}).reduce((sum, count) => sum + count, 0)

  return (
    <div className="dashboard-right">
      <SignalToolbar
        search={search}
        searchRef={searchRef}
        onSearchChange={onSearchChange}
        selectedDateKey={selectedDateKey}
        todayKey={todayKey}
        yesterdayKey={yesterdayKey}
        dateMenuOpen={dateMenuOpen}
        onDateMenuOpenChange={onDateMenuOpenChange}
        dateQuery={dateQuery}
        onDateQueryChange={onDateQueryChange}
        filteredDateOptions={filteredDateOptions}
        metrics={metrics}
        selectedSource={selectedSource}
        selectedTag={selectedTag}
        onClearSource={onClearSource}
        onClearTag={onClearTag}
        onClearAll={onClearAll}
        onToggleToday={onToggleToday}
        onJumpToDate={onJumpToDate}
        onExport={onExport}
        resultCount={resultCount}
        displayedRows={displayedRows}
        isSearchMode={isSearchMode}
        searchTotal={searchTotal}
      />
      <SignalStream
        search={search}
        selectedSource={selectedSource}
        selectedTag={selectedTag}
        displayedRows={displayedRows}
        hasLoadingGroup={hasLoadingGroup}
        groupedRows={groupedRows}
        groupData={groupData}
        collapsedGroups={collapsedGroups}
        setCollapsedGroups={setCollapsedGroups}
        loadGroupData={loadGroupData}
        isSearchMode={isSearchMode}
        timelineRef={timelineRef}
        loadMoreRef={loadMoreRef}
        groupRefs={groupRefs}
        now={now}
        hoveredRowKey={hoveredRowKey}
        onHoverEnter={onHoverEnter}
        onHoverLeave={onHoverLeave}
        onToggleOpen={onToggleOpen}
        onTagClick={onTagClick}
        onClearAll={onClearAll}
        searchLoading={searchLoading}
        loadingMore={loadingMore}
      />
    </div>
  )
}

type SignalToolbarProps = Pick<
  DashboardRightProps,
  | 'search'
  | 'searchRef'
  | 'onSearchChange'
  | 'selectedDateKey'
  | 'todayKey'
  | 'yesterdayKey'
  | 'dateMenuOpen'
  | 'onDateMenuOpenChange'
  | 'dateQuery'
  | 'onDateQueryChange'
  | 'filteredDateOptions'
  | 'metrics'
  | 'selectedSource'
  | 'selectedTag'
  | 'onClearSource'
  | 'onClearTag'
  | 'onClearAll'
  | 'onToggleToday'
  | 'onJumpToDate'
  | 'onExport'
  | 'displayedRows'
  | 'isSearchMode'
  | 'searchTotal'
> & {
  resultCount: number
}

const SignalToolbar = memo(function SignalToolbar({
  search,
  searchRef,
  onSearchChange,
  selectedDateKey,
  todayKey,
  yesterdayKey,
  dateMenuOpen,
  onDateMenuOpenChange,
  dateQuery,
  onDateQueryChange,
  filteredDateOptions,
  metrics,
  selectedSource,
  selectedTag,
  onClearSource,
  onClearTag,
  onClearAll,
  onToggleToday,
  onJumpToDate,
  onExport,
  resultCount,
  isSearchMode,
  searchTotal,
}: SignalToolbarProps) {
  const hasActiveFilter = Boolean(search || selectedSource || selectedTag || selectedDateKey)

  return (
    <div className="controls-bar signal-toolbar">
      <div className="signal-toolbar-head">
        <h2 className="signal-toolbar-title">实时情报流</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span className="result-summary" style={{ marginTop: 0, whiteSpace: 'nowrap' }}>
            <span className="result-count">{resultCount}</span>
            {isSearchMode && <span> / {searchTotal}</span>} 条
          </span>
          <button className="toolbar-icon-btn" onClick={onExport} title="导出 JSON">
            <Download size={14} />
          </button>
        </div>
      </div>

      <div className="signal-search">
        <Search className="signal-search-icon" size={16} color="#8aa3be" />
        <input ref={searchRef} className="search-input search-input-primary" placeholder="搜索标题、来源、标签…（/ 或 Cmd/Ctrl+K）" value={search} onChange={(e) => onSearchChange(e.target.value)} />
        {search && (
          <button className="signal-search-clear" onClick={() => onSearchChange('')} aria-label="清除搜索">
            <X size={14} />
          </button>
        )}
      </div>

      <div className="signal-filter-row">
        <Button active={selectedDateKey === todayKey} onClick={onToggleToday}>今日</Button>
        <DateJumpMenu
          open={dateMenuOpen}
          onOpenChange={onDateMenuOpenChange}
          dateQuery={dateQuery}
          onDateQueryChange={onDateQueryChange}
          filteredDateOptions={filteredDateOptions}
          metrics={metrics}
          todayKey={todayKey}
          yesterdayKey={yesterdayKey}
          onJumpToDate={onJumpToDate}
        />
        <div style={{ flex: 1 }} />
        {hasActiveFilter && (
          <>
            {selectedSource && <Button tone="purple" onClick={onClearSource}>{selectedSource === '__others__' ? '其他来源' : selectedSource} <X size={12} /></Button>}
            {selectedTag && <Button tone="purple" onClick={onClearTag}>#{selectedTag} <X size={12} /></Button>}
            {(search || selectedSource || selectedTag) && <Button onClick={onClearAll}>清除</Button>}
          </>
        )}
      </div>
    </div>
  )
})

type DateJumpMenuProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  dateQuery: string
  onDateQueryChange: (value: string) => void
  filteredDateOptions: string[]
  metrics: Metrics
  todayKey: string
  yesterdayKey: string
  onJumpToDate: (dayKey: string) => void
}

function DateJumpMenu({ open, onOpenChange, dateQuery, onDateQueryChange, filteredDateOptions, metrics, todayKey, yesterdayKey, onJumpToDate }: DateJumpMenuProps) {
  const selectDate = (dayKey: string) => {
    onJumpToDate(dayKey)
    onOpenChange(false)
  }

  return (
    <PopoverMenu
      open={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen)
        if (!nextOpen) onDateQueryChange('')
      }}
      trigger={(
        <button className="date-jump-trigger" aria-expanded={open}>
          <CalendarDays size={13} /> 日期跳转
        </button>
      )}
    >
      <div className="date-jump-panel">
        <input
          className="date-jump-search"
          value={dateQuery}
          onChange={(e) => onDateQueryChange(e.target.value)}
          placeholder="搜索日期，例如 4/21"
        />
        <div className="date-jump-quick">
          {[todayKey, yesterdayKey].map((dayKey) => (
            <button key={dayKey} onClick={() => selectDate(dayKey)}>
              {formatGroupTitle(dayKey, todayKey, yesterdayKey)}
            </button>
          ))}
        </div>
        <MenuPanel className="date-jump-list">
          {filteredDateOptions.map((dayKey) => (
            <button key={dayKey} onClick={() => selectDate(dayKey)}>
              <span>{formatGroupTitle(dayKey, todayKey, yesterdayKey)}</span>
              <strong>{metrics.daily_totals?.[dayKey] || 0}</strong>
            </button>
          ))}
        </MenuPanel>
      </div>
    </PopoverMenu>
  )
}

type SignalStreamProps = Pick<
  DashboardRightProps,
  | 'search'
  | 'selectedSource'
  | 'displayedRows'
  | 'hasLoadingGroup'
  | 'groupedRows'
  | 'groupData'
  | 'collapsedGroups'
  | 'setCollapsedGroups'
  | 'loadGroupData'
  | 'isSearchMode'
  | 'timelineRef'
  | 'loadMoreRef'
  | 'groupRefs'
  | 'now'
  | 'hoveredRowKey'
  | 'selectedTag'
  | 'onHoverEnter'
  | 'onHoverLeave'
  | 'onToggleOpen'
  | 'onTagClick'
  | 'onClearAll'
  | 'searchLoading'
  | 'loadingMore'
>

const SignalStream = memo(function SignalStream({
  search,
  selectedSource,
  selectedTag,
  displayedRows,
  hasLoadingGroup,
  groupedRows,
  groupData,
  collapsedGroups,
  setCollapsedGroups,
  loadGroupData,
  isSearchMode,
  timelineRef,
  loadMoreRef,
  groupRefs,
  now,
  hoveredRowKey,
  onHoverEnter,
  onHoverLeave,
  onToggleOpen,
  onTagClick,
  onClearAll,
  searchLoading,
  loadingMore,
}: SignalStreamProps) {
  return (
    <div className="timeline-container custom-scrollbar" ref={timelineRef}>
      <section className="timeline" role="log" aria-live="polite" aria-label="信号列表">
        {displayedRows.length === 0 && !hasLoadingGroup && (
          <EmptyState search={search} selectedSource={selectedSource} selectedTag={selectedTag} onClearAll={onClearAll} />
        )}
        {groupedRows.map((group) => {
          const groupState = groupData[group.id]
          const isLoading = isSearchMode ? false : (groupState?.loading ?? false)
          const isLoaded = isSearchMode ? true : (groupState?.loaded ?? false)
          return (
            <SignalGroup
              key={group.id}
              group={group}
              isLoading={isLoading}
              isLoaded={isLoaded}
              isSearchMode={isSearchMode}
              collapsed={Boolean(collapsedGroups[group.id])}
              onToggle={() => {
                if (!isSearchMode && !isLoaded && !isLoading) {
                  void loadGroupData(group.id)
                  setCollapsedGroups((prev) => ({ ...prev, [group.id]: false }))
                  return
                }
                setCollapsedGroups((prev) => ({ ...prev, [group.id]: !prev[group.id] }))
              }}
              refCallback={(el) => { groupRefs.current[group.id] = el }}
              now={now}
              hoveredRowKey={hoveredRowKey}
              selectedTag={selectedTag}
              onHoverEnter={onHoverEnter}
              onHoverLeave={onHoverLeave}
              onToggleOpen={onToggleOpen}
              onTagClick={onTagClick}
            />
          )
        })}
        <div ref={loadMoreRef} className="timeline-sentinel" />
        {searchLoading && isSearchMode && <StreamStatus>正在检索全量数据...</StreamStatus>}
        {loadingMore && <StreamStatus>正在加载更多...</StreamStatus>}
      </section>
    </div>
  )
})

type SignalGroupProps = {
  group: FeedGroupView
  isLoading: boolean
  isLoaded: boolean
  isSearchMode: boolean
  collapsed: boolean
  onToggle: () => void
  refCallback: (el: HTMLDivElement | null) => void
  now: Date | null
  hoveredRowKey: string | null
  selectedTag: string | null
  onHoverEnter: (key: string) => void
  onHoverLeave: (key: string) => void
  onToggleOpen: (key: string) => void
  onTagClick: (tag: string) => void
}

const SignalGroup = memo(function SignalGroup({ group, isLoading, collapsed, onToggle, refCallback, now, hoveredRowKey, selectedTag, onHoverEnter, onHoverLeave, onToggleOpen, onTagClick }: SignalGroupProps) {
  return (
    <div className="feed-group" ref={refCallback}>
      <button className="feed-group-head" onClick={onToggle}>
        <span className="feed-group-title">{group.title}</span>
        <span className="feed-group-meta">{group.total} 条 {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}</span>
      </button>
      {!collapsed && (
        <div className="feed-group-body">
          {isLoading && group.items.length === 0 && (
            <div className="group-loading">正在加载...</div>
          )}
          {group.items.map((row, idx) => {
            const rowKey = row.id || `${row.url}|${row.time}|${row.title || 'untitled'}`
            return (
              <FeedCard
                key={`${group.id}-${rowKey}`}
                row={row}
                now={now}
                hoveredRowKey={hoveredRowKey}
                selectedTag={selectedTag}
                onHoverEnter={onHoverEnter}
                onHoverLeave={onHoverLeave}
                onToggleOpen={onToggleOpen}
                onTagClick={onTagClick}
              />
            )
          })}
        </div>
      )}
    </div>
  )
})

type EmptyStateProps = {
  search: string
  selectedSource: string | null
  selectedTag: string | null
  onClearAll: () => void
}

const EmptyState = memo(function EmptyState({ search, selectedSource, selectedTag, onClearAll }: EmptyStateProps) {
  const reason = search.trim()
    ? `「${search.trim()}」`
    : selectedTag
      ? `#${selectedTag}`
      : selectedSource
        ? `「${selectedSource === '__others__' ? '其他来源' : selectedSource}」`
        : null

  return (
    <div className="empty-state">
      <div className="empty-state-icon"><Inbox size={40} /></div>
      <div className="empty-state-text">{reason ? `${reason} 暂无匹配信号` : '暂无信号数据'}</div>
      {reason && (
        <button className="empty-state-clear" onClick={onClearAll}>
          清除所有筛选
        </button>
      )}
    </div>
  )
})

const StreamStatus = memo(function StreamStatus({ children }: { children: ReactNode }) {
  return (
    <div className="stream-status">
      <span className="pulse-indicator">
        <span className="dot" /><span className="dot" /><span className="dot" />
      </span>
      {children}
    </div>
  )
})
