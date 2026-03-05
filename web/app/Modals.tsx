'use client'

import { KeyRound, Save, Trash2, Send } from 'lucide-react'
import type { Row, PendingExport, ExportScope } from './types'

// ─── Export Preview Modal ────────────────────────────────────────────────────

type ExportModalProps = {
  pendingExport: PendingExport
  onClose: () => void
  selectedExportKeys: string[]
  setSelectedExportKeys: React.Dispatch<React.SetStateAction<string[]>>
  exportScope: ExportScope
  cuboxBusy: boolean
  onExportToCubox: (rows: Row[], label: string) => Promise<void>
  onDownloadJson: (rows: Row[], label: string) => void
  onUpdateExportScope: (scope: ExportScope) => void
}

export function ExportModal({
  pendingExport,
  onClose,
  selectedExportKeys,
  setSelectedExportKeys,
  exportScope,
  cuboxBusy,
  onExportToCubox,
  onDownloadJson,
  onUpdateExportScope,
}: ExportModalProps) {
  if (!pendingExport) return null

  return (
    <div className="export-overlay" role="dialog" aria-modal="true">
      <div className="export-overlay-backdrop" onClick={onClose} />
      <section className="glass export-preview export-preview-modal">
        <div className="export-preview-head">
          <div className="export-preview-title-wrap">
            <h3 style={{ margin: 0, fontSize: 16 }}>
              导出预览：{pendingExport.label}（{pendingExport.rows.length} 条）
            </h3>
            <span className="export-selected-inline">已选 {selectedExportKeys.length}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="filter-btn" onClick={onClose} disabled={cuboxBusy}>
              取消
            </button>
            <button
              className="filter-btn active"
              onClick={async () => {
                const selectedRows = pendingExport.rows.filter((r, idx) =>
                  selectedExportKeys.includes(`${r.id || r.url}|${r.time}|${idx}`)
                )
                await onExportToCubox(selectedRows, pendingExport.label)
                onClose()
              }}
              disabled={cuboxBusy || selectedExportKeys.length === 0}
            >
              <Send size={13} /> 导出到 Cubox
            </button>
            <button
              className="filter-btn"
              onClick={() => {
                const selectedRows = pendingExport.rows.filter((r, idx) =>
                  selectedExportKeys.includes(`${r.id || r.url}|${r.time}|${idx}`)
                )
                onDownloadJson(selectedRows, pendingExport.label)
              }}
              disabled={selectedExportKeys.length === 0}
            >
              导出 JSON
            </button>
          </div>
        </div>

        <div className="export-scope-row">
          <span className="export-scope-label">范围：</span>
          <button className={`filter-btn ${exportScope === 'current' ? 'active' : ''}`} onClick={() => onUpdateExportScope('current')}>当前筛选</button>
          <button className={`filter-btn ${exportScope === 'high' ? 'active' : ''}`} onClick={() => onUpdateExportScope('high')}>高价值</button>
          <button className={`filter-btn ${exportScope === 'today' ? 'active' : ''}`} onClick={() => onUpdateExportScope('today')}>今日</button>
          <button
            className="filter-btn"
            onClick={() => setSelectedExportKeys(pendingExport.rows.map((r, idx) => `${r.id || r.url}|${r.time}|${idx}`))}
          >
            全选
          </button>
          <button className="filter-btn" onClick={() => setSelectedExportKeys([])}>清空</button>
        </div>

        <div className="export-preview-list">
          {pendingExport.rows.slice(0, 40).map((r, i) => {
            const rowSelectKey = `${r.id || r.url}|${r.time}|${i}`
            const checked = selectedExportKeys.includes(rowSelectKey)
            const tags = Array.from(new Set([...(r.tags || []), pendingExport.label])).slice(0, 8)
            return (
              <div key={`${r.id || r.url}-${i}`} className="export-preview-item">
                <label className="export-check">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => {
                      setSelectedExportKeys((prev) =>
                        e.target.checked ? [...prev, rowSelectKey] : prev.filter((k) => k !== rowSelectKey)
                      )
                    }}
                  />
                </label>
                <a href={r.url} target="_blank" rel="noreferrer" className="export-preview-title">
                  {r.title || r.hidden_signal || r.url}
                </a>
                <div className="export-preview-meta">
                  <span>{r.url}</span>
                  <span>tags: {tags.join(', ') || '无'}</span>
                </div>
              </div>
            )
          })}
          {pendingExport.rows.length > 40 && (
            <div className="export-preview-more">还有 {pendingExport.rows.length - 40} 条将在确认后导出</div>
          )}
        </div>
      </section>
    </div>
  )
}

// ─── Settings Modal ──────────────────────────────────────────────────────────

type SettingsModalProps = {
  show: boolean
  onClose: () => void
  cuboxConfigured: boolean
  cuboxKeyInput: string
  setCuboxKeyInput: React.Dispatch<React.SetStateAction<string>>
  cuboxFolder: string
  setCuboxFolder: React.Dispatch<React.SetStateAction<string>>
  cuboxBusy: boolean
  onSave: () => Promise<void>
  onClear: () => Promise<void>
}

export function SettingsModal({
  show,
  onClose,
  cuboxConfigured,
  cuboxKeyInput,
  setCuboxKeyInput,
  cuboxFolder,
  setCuboxFolder,
  cuboxBusy,
  onSave,
  onClear,
}: SettingsModalProps) {
  if (!show) return null

  return (
    <div className="export-overlay" role="dialog" aria-modal="true">
      <div className="export-overlay-backdrop" onClick={onClose} />
      <section className="glass settings-modal">
        <div className="settings-head">
          <h3 style={{ margin: 0, fontSize: 16 }}>Cubox 配置</h3>
          <button className="filter-btn" onClick={onClose}>关闭</button>
        </div>

        <section className="settings-section">
          <div className="settings-row">
            <div className="insight-key-state">
              <KeyRound size={15} />
              <span>{cuboxConfigured ? 'Cubox 已连接' : 'Cubox 未连接'}</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <a className="cubox-get-link" href="https://help.cubox.pro/save/89d3/" target="_blank" rel="noreferrer">
                获取 Cubox Key
              </a>
              {cuboxConfigured && (
                <button className="filter-btn" onClick={onClear} disabled={cuboxBusy}>
                  <Trash2 size={13} /> 清除
                </button>
              )}
            </div>
          </div>

          <section className="cubox-editor">
            <div className="cubox-field">
              <label className="cubox-field-label">Cubox Key 或完整 API URL</label>
              <input
                className="search-input"
                placeholder="例如：xxyyzz... 或 https://cubox.pro/c/api/save/..."
                value={cuboxKeyInput}
                onChange={(e) => setCuboxKeyInput(e.target.value)}
              />
            </div>
            <div className="cubox-field">
              <label className="cubox-field-label">导出文件夹</label>
              <input
                className="search-input"
                placeholder="例如：RSS Inbox"
                value={cuboxFolder}
                onChange={(e) => setCuboxFolder(e.target.value)}
              />
            </div>
            <button className="cta-btn cubox-save-btn" onClick={onSave} disabled={cuboxBusy}>
              <Save size={13} /> 保存配置
            </button>
          </section>
        </section>
      </section>
    </div>
  )
}
