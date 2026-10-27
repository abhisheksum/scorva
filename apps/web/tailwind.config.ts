import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        background: '#07111F',
        surface: {
          DEFAULT: '#0D1A2B',
          elevated: '#112139',
          border: '#24364D',
          hover: '#162B45',
        },
        sidebar: '#0A1424',
        primary: {
          DEFAULT: '#2784FF',
          hover: '#1A6FE8',
          muted: '#1D4ED8',
        },
        text: {
          primary: '#F3F6FC',
          secondary: '#91A4BE',
          muted: '#5A7294',
        },
        status: {
          success: '#00D6A0',
          warning: '#F5B82E',
          error: '#FF5C66',
          danger: '#FF5C66',
          info: '#38BDF8',
        },
        accent: {
          purple: '#A855F7',
          cyan: '#22D3EE',
          amber: '#F5B82E',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Plus Jakarta Sans', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'surface-elevated': '0 4px 20px -2px rgba(0, 0, 0, 0.5)',
        'card': '0 1px 3px rgba(0, 0, 0, 0.3)',
      },
    },
  },
  plugins: [],
};

export default config;
