/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        alien: {
          bg: '#0a0a0f',
          panel: '#0d1117',
          border: '#1a2332',
          cyan: '#00f0ff',
          magenta: '#ff00ff',
          green: '#00ff88',
          yellow: '#ffdd00',
          red: '#ff3355',
          purple: '#7b2fff',
          blue: '#3366ff',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
        'scan': 'scan 3s linear infinite',
        'dataflow': 'dataflow 1s linear infinite',
        'slide-in': 'slideIn 0.25s ease-out',
        'slide-up': 'slideUp 0.28s ease-out',
      },
      keyframes: {
        slideIn: {
          '0%': { opacity: '0', transform: 'translateX(-12px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 5px var(--glow-color, #00f0ff)' },
          '50%': { boxShadow: '0 0 20px var(--glow-color, #00f0ff), 0 0 40px var(--glow-color, #00f0ff)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        scan: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100%)' },
        },
        dataflow: {
          '0%': { strokeDashoffset: '20' },
          '100%': { strokeDashoffset: '0' },
        },
      },
    },
  },
  plugins: [],
};
