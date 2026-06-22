/** @type {import('tailwindcss').Config} */
module.exports = {
  // Tailwind qaysi fayllardan class'larni qidirishini ko'rsatamiz
  content: [
    "./templates/**/*.html",
    "./**/*.html"
  ],
  theme: {
    extend: {
      // Sizning oldingi base.html dagi maxsus ranglaringiz
      colors: {
        'drama-green': '#00cc4c',
        'drama-dark': '#0a0a0a',
      },
      fontFamily: {
        'inter': ['Inter', 'sans-serif']
      }
    },
  },
  plugins: [],
}
