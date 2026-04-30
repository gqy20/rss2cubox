'use client'

import type { Dispatch, ReactNode, RefObject, SetStateAction } from 'react'
import { AlertCircle, CalendarDays, Check, ChevronDown, ChevronUp, Copy, Download, Filter, Search } from 'lucide-react'
import FeedCard from './FeedCard'
import type { Metrics, Row, InsightKey } from './types'
import { AnimatedNumber, formatGroupTitle, Logo } from './utils'
import { Button, MenuPanel, PopoverMenu } from './ui'
import type { InsightHistoryItem } from '../lib/signalStore'

export type ParsedInsightItem = {
  title: string
  content?: string
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
    <div className="header-container" style={{ marginBottom: 18 }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Logo size={40} />
          <h1 className="h1">RSS 信号控制台</h1>
        </div>
        <div className="muted" style={{ marginTop: 6, marginLeft: 52 }}>
          <span suppressHydrationWarning>最后更新：{generatedAt}</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div className="live-status">
          <span className="status-dot" />
          <span>批量分析结果</span>
        </div>
        <Button onClick={onExport}>
          <Download size={13} /> 导出 JSON
        </Button>
      </div>
    </div>
  )
}

function KpiGrid({ items }: { items: readonly KpiItem[] }) {
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
}

type InsightBriefingProps = {
  activePanel: InsightPanel
  visiblePanels: InsightPanel[]
  onSelectInsightKey: (key: InsightKey) => void
  onCopy: (title: string, items: ParsedInsightItem[]) => void
}

function InsightBriefing({ activePanel, visiblePanels, onSelectInsightKey, onCopy }: InsightBriefingProps) {
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
      <ol className="briefing-list">
        {activePanel.items.slice(0, 5).map((item, i) => (
          <li key={`${activePanel.key}-${i}-${item.title}`}>
            <span className="briefing-index">{String(i + 1).padStart(2, '0')}</span>
            <div>
              <div className="briefing-item-title">{item.title}</div>
              {item.content && <p className="briefing-item-content">{item.content}</p>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function DeferredCharts({ onLoad }: { onLoad: () => void }) {
  return (
    <section className="charts-grid" style={{ marginBottom: 18 }}>
      <div className="glass chart-card chart-deferred-card">
        <div className="chart-deferred-title">查看趋势</div>
        <p className="chart-deferred-copy">展开最近信号的总量变化与已分析占比。</p>
        <Button onClick={onLoad}>立即加载图表</Button>
      </div>
      <div className="glass chart-card chart-deferred-card">
        <div className="chart-deferred-title">查看来源分布</div>
        <p className="chart-deferred-copy">按来源筛选情报流，快速聚焦高频信号源。</p>
        <Button onClick={onLoad}>立即加载图表</Button>
      </div>
    </section>
  )
}

function ActionMessage({ message }: { message: { type: 'success' | 'error'; text: string } }) {
  return (
    <div className={`action-message ${message.type === 'success' ? 'success' : 'error'}`}>
      {message.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
      <span>{message.text}</span>
    </div>
  )
}

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
        filter={filter}
        onFilterChange={onFilterChange}
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
  | 'filter'
  | 'onFilterChange'
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

function SignalToolbar({
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
  resultCount,
  isSearchMode,
  searchTotal,
}: SignalToolbarProps) {
  return (
    <div className="controls-bar" style={{ borderBottom: '1px solid var(--panel-border)', paddingBottom: 14, marginBottom: 0, flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
        <h2 style={{ fontSize: '20px', margin: 0, fontWeight: 700 }}>实时情报流</h2>
      </div>

      <div style={{ width: '100%', position: 'relative' }}>
        <Search size={16} color="#8aa3be" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
        <input ref={searchRef} className="search-input search-input-primary" placeholder="搜索标题、来源、标签…（/ 或 Cmd/Ctrl+K）" value={search} onChange={(e) => onSearchChange(e.target.value)} />
        {search && (
          <button onClick={() => onSearchChange('')} style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#8aa3be', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 0 }}>
            ×
          </button>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', flexWrap: 'wrap' }}>
        <Filter size={15} color="#8aa3be" />
        <Button active={filter === 'analyzed'} onClick={() => onFilterChange('analyzed')}>已分析</Button>
        <Button active={filter === 'high_value'} onClick={() => onFilterChange('high_value')}>高价值</Button>
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
        <Button onClick={onExport}>
          <Download size={13} /> 导出
        </Button>
        {selectedSource && <Button tone="purple" onClick={onClearSource}>{selectedSource === '__others__' ? '其他来源' : selectedSource} ×</Button>}
        {selectedTag && <Button tone="purple" onClick={onClearTag}>#{selectedTag} ×</Button>}
        {(search || selectedSource || selectedTag || filter !== 'all') && <Button onClick={onClearAll}>清除</Button>}
      </div>

      <div style={{ fontSize: 12, color: '#8aa3be', width: '100%' }}>
        共 <span style={{ color: '#2dd4bf', fontWeight: 600 }}>{resultCount}</span>
        {isSearchMode && <span> / {searchTotal}</span>} 条结果
      </div>
    </div>
  )
}

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

function SignalStream({
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
    <div className="timeline-container" ref={timelineRef}>
      <section className="timeline" style={{ marginTop: 12 }}>
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
        <div ref={loadMoreRef} style={{ height: 1 }} />
        {searchLoading && isSearchMode && <StreamStatus>正在检索全量数据...</StreamStatus>}
        {loadingMore && <StreamStatus>正在加载更多...</StreamStatus>}
      </section>
    </div>
  )
}

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

function SignalGroup({ group, isLoading, collapsed, onToggle, refCallback, now, hoveredRowKey, selectedTag, onHoverEnter, onHoverLeave, onToggleOpen, onTagClick }: SignalGroupProps) {
  return (
    <div className="feed-group" ref={refCallback}>
      <button className="feed-group-head" onClick={onToggle}>
        <span className="feed-group-title">{group.title}</span>
        <span className="feed-group-meta">{group.total} 条</span>
        {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>
      {!collapsed && (
        <div className="feed-group-body">
          {isLoading && group.items.length === 0 && (
            <div style={{ color: '#8aa3be', fontSize: 12, padding: '8px 2px 10px' }}>正在加载...</div>
          )}
          {group.items.map((row, idx) => {
            const rowKey = row.id || `${row.url}|${row.time}|${row.title || 'untitled'}`
            return (
              <FeedCard
                key={`${group.id}-${rowKey}-${idx}`}
                row={row}
                idx={idx}
                groupId={group.id}
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
}

type EmptyStateProps = {
  search: string
  selectedSource: string | null
  selectedTag: string | null
  onClearAll: () => void
}

function EmptyState({ search, selectedSource, selectedTag, onClearAll }: EmptyStateProps) {
  const reason = search.trim()
    ? `「${search.trim()}」`
    : selectedTag
      ? `#${selectedTag}`
      : selectedSource
        ? `「${selectedSource === '__others__' ? '其他来源' : selectedSource}」`
        : null

  return (
    <div style={{ textAlign: 'center', padding: '60px 20px', color: '#8aa3be' }}>
      <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.4 }}>◎</div>
      <div style={{ fontSize: 14 }}>{reason ? `${reason} 暂无匹配信号` : '暂无信号数据'}</div>
      {reason && (
        <button onClick={onClearAll} style={{ marginTop: 12, background: 'none', border: '1px solid #8aa3be', color: '#8aa3be', padding: '4px 12px', borderRadius: 20, cursor: 'pointer', fontSize: 13 }}>
          清除所有筛选
        </button>
      )}
    </div>
  )
}

function StreamStatus({ children }: { children: ReactNode }) {
  return (
    <div style={{ textAlign: 'center', fontSize: 12, color: '#8aa3be', padding: '8px 0 14px' }}>
      {children}
    </div>
  )
}
