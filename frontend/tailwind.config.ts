import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: 'var(--color-brand-primary)',
          secondary: 'var(--color-brand-secondary)',
          accent: 'var(--color-brand-accent)',
          highlight: 'var(--color-brand-highlight)',
        },
        surface: {
          base: 'var(--color-surface)',
          muted: 'var(--color-surface-muted)',
          elevated: 'var(--color-surface-elevated)',
          translucent: 'var(--color-surface-translucent)',
        },
        text: {
          primary: 'var(--color-text-primary)',
          secondary: 'var(--color-text-secondary)',
          tertiary: 'var(--color-text-tertiary)',
          inverse: 'var(--color-text-inverse)',
        },
        success: '#2fb470',
        warning: '#f4b040',
        danger: '#e2555d',
        info: '#2f6fed',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif'],
        display: ['"Space Grotesk"', '"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        subtle: '0 12px 32px -16px rgba(9, 25, 54, 0.18)',
        brand: '0 32px 80px -48px rgba(11, 31, 60, 0.45)',
      },
      borderRadius: {
        '3xl': '2rem',
        '4xl': '2.5rem',
      },
      backgroundImage: {
        'brand-diagonal':
          'linear-gradient(135deg, rgba(47, 111, 237, 0.12) 0%, rgba(11, 31, 60, 0) 55%)',
        'brand-radial':
          'radial-gradient(circle at top left, rgba(154, 200, 255, 0.45), transparent 55%)',
      },
      spacing: {
        13: '3.25rem',
        18: '4.5rem',
      },
      maxWidth: {
        '8xl': '88rem',
      },
      screens: {
        '3xl': '1600px',
      },
      transitionProperty: {
        'colors-position': 'background-color, border-color, color, fill, stroke, opacity, box-shadow, transform',
      },
    },
  },
  plugins: [],
} satisfies Config
