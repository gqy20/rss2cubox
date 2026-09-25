'use client'
import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

/** Right-side reading drawer over a dimmed backdrop: Esc / backdrop / close
 *  button dismiss, focus is trapped inside and returned to the trigger. */
export default function Drawer({
  open,
  onClose,
  label,
  header,
  children,
}: {
  open: boolean
  onClose: () => void
  label: string
  header?: ReactNode
  children: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const restore = document.activeElement as HTMLElement | null,
      previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const focusables = [
        ...(panel.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ) ?? []),
      ]
      if (!focusables.length) return
      const first = focusables[0],
        last = focusables[focusables.length - 1],
        active = document.activeElement
      if (e.shiftKey && (active === first || active === panel.current)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKey)
      restore?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        ref={panel}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-head">
          {header}
          <button
            type="button"
            className="icon-button drawer-close"
            aria-label="关闭详情"
            title="关闭详情（Esc）"
            onClick={onClose}
          >
            <X size={17} />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  )
}
