'use client'

import type { ButtonHTMLAttributes, ReactNode } from 'react'

function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean
  iconOnly?: boolean
  tone?: 'default' | 'accent' | 'purple'
}

export function Button({ active, iconOnly, tone = 'default', className, children, ...props }: ButtonProps) {
  return (
    <button
      className={cx(
        'filter-btn',
        active && 'active',
        iconOnly && 'icon-only-btn',
        tone === 'purple' && 'source-filter-active',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

type SegmentedControlProps<T extends string> = {
  value: T
  options: Array<{ value: T; label: ReactNode }>
  onChange: (value: T) => void
  ariaLabel: string
  className?: string
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div className={cx('segmented-control', className)} role="radiogroup" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? 'active' : ''}
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

type MenuPanelProps = {
  children: ReactNode
  className?: string
}

export function MenuPanel({ children, className }: MenuPanelProps) {
  return <div className={cx('menu-panel', className)}>{children}</div>
}
