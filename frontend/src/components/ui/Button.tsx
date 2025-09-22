import React from 'react'
import { cn } from '../../lib/utils'

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'outline'
  size?: 'sm' | 'md'
  icon?: React.ReactNode
}

export default function Button({
  variant = 'primary',
  size = 'md',
  icon,
  className,
  children,
  ...props
}: ButtonProps) {
  const variantClasses: Record<typeof variant, string> = {
    primary:
      'bg-brand-accent text-white border border-brand-accent shadow-brand hover:bg-brand-accent/90 hover:shadow-brand/70',
    secondary:
      'bg-white text-brand-primary border border-white/40 shadow-subtle hover:bg-brand-highlight/10 hover:text-brand-accent',
    ghost:
      'bg-transparent text-white border border-white/30 hover:bg-white/10',
    outline:
      'bg-transparent text-brand-primary border border-brand-accent hover:bg-brand-accent/10',
  }

  const sizeClasses: Record<typeof size, string> = {
    md: 'px-5 py-2.5 text-sm',
    sm: 'px-3 py-1.5 text-xs uppercase tracking-[0.18em] font-semibold',
  }

  return (
    <button
      className={cn(
        'inline-flex items-center gap-2 rounded-full font-semibold transition-all duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-accent disabled:cursor-not-allowed disabled:opacity-60',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {icon && <span className="h-4 w-4">{icon}</span>}
      <span>{children}</span>
    </button>
  )
}
