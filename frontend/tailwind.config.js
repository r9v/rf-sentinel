/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rf: {
          bg: '#0a0e1a',
          panel: '#0f1525',
          border: '#1e2840',
          accent: '#00d4ff',
          'accent-dim': '#006880',
          green: '#00ff88',
          amber: '#ffa500',
          red: '#ff4444',
          text: '#e0e0e0',
          muted: '#808090',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
