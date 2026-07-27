/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'Poppins', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        /* Kept as the legacy token name so every existing screen adopts the new brand without regressions. */
        tomato: {
          50: '#0d2142',
          100: '#123064',
          200: '#19458f',
          300: '#2760c8',
          400: '#4d82ff',
          500: '#3b75ff',
          600: '#2f6bff',
          700: '#2555d4',
          800: '#1f46ad',
          900: '#1b3b8c',
          950: '#102452',
        },
        /* The app previously used the gray scale semantically: 50 for canvas and 900 for text. */
        gray: {
          50: '#081220',
          100: '#17243a',
          200: '#263a59',
          300: '#3d5578',
          400: '#71819c',
          500: '#a8b3c7',
          600: '#c8d2e1',
          700: '#dce4ef',
          800: '#edf2f7',
          900: '#f8fafc',
          950: '#ffffff',
        },
        navy: {
          950: '#050b14',
          900: '#081220',
          800: '#0d1728',
          700: '#111a2e',
          600: '#17243a',
          500: '#1a2a44',
          400: '#263a59',
        },
        brand: {
          blue: '#2f6bff',
          light: '#6aa7ff',
          gold: '#f2c14e',
          white: '#f8fafc',
        },
      },
      boxShadow: {
        brand: '0 18px 55px rgba(0, 0, 0, 0.28)',
        glow: '0 0 0 1px rgba(106, 167, 255, 0.08), 0 14px 42px rgba(10, 37, 78, 0.34)',
      },
      animation: {
        'slide-in': 'slideIn 0.3s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
        'bounce-in': 'bounceIn 0.4s ease-out',
        'soft-pulse': 'softPulse 2.4s ease-in-out infinite',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateY(-10px)', opacity: 0 },
          '100%': { transform: 'translateY(0)', opacity: 1 },
        },
        fadeIn: {
          '0%': { opacity: 0 },
          '100%': { opacity: 1 },
        },
        bounceIn: {
          '0%': { transform: 'scale(0.9)', opacity: 0 },
          '60%': { transform: 'scale(1.05)' },
          '100%': { transform: 'scale(1)', opacity: 1 },
        },
        softPulse: {
          '0%, 100%': { opacity: 0.72 },
          '50%': { opacity: 1 },
        },
      },
    },
  },
  plugins: [],
}
