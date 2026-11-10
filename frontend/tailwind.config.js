export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'Noto Sans TC', 'system-ui', 'sans-serif'] },
      colors: { ink: '#101827', surface: '#f5f7fb', primary: '#6255db' },
      boxShadow: { soft: '0 12px 44px rgba(29,39,75,0.06)' }
    }
  },
  plugins: []
}
