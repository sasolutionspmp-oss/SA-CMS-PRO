import React from 'react'
import { cn } from '../../lib/utils'

type IconProps = React.SVGProps<SVGSVGElement> & {
  className?: string
}

function IconBase({ className, children, viewBox = '0 0 24 24', ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox={viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('h-5 w-5', className)}
      {...props}
    >
      {children}
    </svg>
  )
}

export const MenuIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h10" />
  </IconBase>
)

export const CloseIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M6 6l12 12" />
    <path d="M18 6l-12 12" />
  </IconBase>
)

export const IngestIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 3v12" />
    <path d="m7 10 5 5 5-5" />
    <path d="M5 19h14" />
  </IconBase>
)

export const SearchIcon = (props: IconProps) => (
  <IconBase {...props}>
    <circle cx={11} cy={11} r={6} />
    <path d="m20 20-3.5-3.5" />
  </IconBase>
)

export const EstimateIcon = (props: IconProps) => (
  <IconBase {...props}>
    <rect x={4} y={4} width={16} height={16} rx={3} />
    <path d="M8 9h8" />
    <path d="M8 12h5" />
    <path d="M8 15h3" />
  </IconBase>
)

export const ComplianceIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 3 5 6v6c0 5 7 9 7 9s7-4 7-9V6z" />
    <path d="m9 12 2 2 4-4" />
  </IconBase>
)

export const PMIcon = (props: IconProps) => (
  <IconBase {...props}>
    <rect x={3} y={4} width={18} height={16} rx={3} />
    <path d="M3 9h18" />
    <path d="M9 9v11" />
    <path d="M15 9v11" />
  </IconBase>
)

export const SafetyIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 3 5.5 6v6.5c0 4.5 3.3 7.8 6.5 9.5 3.2-1.7 6.5-5 6.5-9.5V6z" />
    <path d="M9.5 11.5h5" />
    <path d="M12 9v5" />
  </IconBase>
)

export const FinanceIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M5 19h14" />
    <path d="M7 15l3-4 3 3 4-6" />
    <path d="M6 5h2" />
    <path d="M16 5h2" />
  </IconBase>
)

export const SettingsIcon = (props: IconProps) => (
  <IconBase {...props}>
    <circle cx={12} cy={12} r={3} />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 5 15.4a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 7.6 5a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </IconBase>
)

export const HistoryIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M3 12a9 9 0 1 1 3 6.708" />
    <path d="M3 12h3" />
    <path d="M12 7v5l3 3" />
  </IconBase>
)

export const BellIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M18 14v-3a6 6 0 0 0-12 0v3" />
    <path d="M5 14h14" />
    <path d="M10 18a2 2 0 0 0 4 0" />
  </IconBase>
)

export const SparkIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 3v4" />
    <path d="m5.5 7 2.8 2.8" />
    <path d="M3 12h4" />
    <path d="m5.5 17 2.8-2.8" />
    <path d="M12 21v-4" />
    <path d="m18.5 17-2.8-2.8" />
    <path d="M21 12h-4" />
    <path d="m18.5 7-2.8 2.8" />
  </IconBase>
)

export const UploadIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 17V7" />
    <path d="m7 12 5-5 5 5" />
    <path d="M5 19h14" />
  </IconBase>
)

export const TrendUpIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="m3 17 6-6 4 4 8-8" />
    <path d="M21 7h-6" />
  </IconBase>
)

export const TrendDownIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="m3 7 6 6 4-4 8 8" />
    <path d="M21 17h-6" />
  </IconBase>
)

export const ShieldCheckIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 3 5 6v6c0 5 7 9 7 9s7-4 7-9V6z" />
    <path d="m9 12 2 2 4-4" />
  </IconBase>
)

export const LayersIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="m12 3 9 5-9 5-9-5z" />
    <path d="m3 12 9 5 9-5" />
    <path d="m3 17 9 5 9-5" />
  </IconBase>
)

export const ClockIcon = (props: IconProps) => (
  <IconBase {...props}>
    <circle cx={12} cy={12} r={8} />
    <path d="M12 8v4l2.5 2.5" />
  </IconBase>
)

export const DocumentIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M7 3h8l4 4v14H7z" />
    <path d="M15 3v4h4" />
    <path d="M9 13h6" />
    <path d="M9 17h6" />
  </IconBase>
)

export const UsersIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
    <circle cx={9} cy={7} r={3} />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </IconBase>
)

export const PulseIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M3 12h3l2-5 4 10 2-5h7" />
  </IconBase>
)

export const CheckIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="m5 13 4 4L19 7" />
  </IconBase>
)

export const AlertIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
    <path d="m10.29 3.86-7.53 13A1 1 0 0 0 3.58 19h16.84a1 1 0 0 0 .86-1.5l-7.53-13a1 1 0 0 0-1.72 0Z" />
  </IconBase>
)

export const GlobeIcon = (props: IconProps) => (
  <IconBase {...props}>
    <circle cx={12} cy={12} r={9} />
    <path d="M3 12h18" />
    <path d="M12 3a15.3 15.3 0 0 1 4 9 15.3 15.3 0 0 1-4 9 15.3 15.3 0 0 1-4-9 15.3 15.3 0 0 1 4-9z" />
  </IconBase>
)

export const LayersStackedIcon = (props: IconProps) => (
  <IconBase {...props}>
    <path d="m12 4 8 4-8 4-8-4 8-4z" />
    <path d="m4 12 8 4 8-4" />
    <path d="m4 16 8 4 8-4" />
  </IconBase>
)
