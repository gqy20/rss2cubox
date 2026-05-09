'use client'

import type { ButtonHTMLAttributes, ReactNode } from 'react'
import * as Popover from '@radix-ui/react-popover'

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
  return <div className={cx('menu-panel custom-scrollbar', className)}>{children}</div>
}

type PopoverMenuProps = {
  trigger: ReactNode
  children: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  align?: 'start' | 'center' | 'end'
  className?: string
}

export function PopoverMenu({
  trigger,
  children,
  open,
  onOpenChange,
  align = 'start',
  className,
}: PopoverMenuProps) {
  return (
    <Popover.Root open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger asChild>{trigger}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={cx('popover-panel', className)} align={align} sideOffset={8}>
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
