/** @type {import('tailwindcss').Config} */
module.exports = {
  // FAQAT loyiha shablonlari va JS — `./**/*.html` OLIB TASHLANDI [P5-T1]
  // (u env/, node_modules/ ni ham skanerlab build'ni sekinlashtirardi).
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        // base.html tarixiy nomlari
        'drama-green': '#00cc4c',
        'drama-dark': '#0a0a0a',
        // base-users.html Play-CDN inline konfiguratsiyasidan ko'chirildi [P5-T1]
        brand: '#00cc4c',
        dark: '#111111',
        card: '#1a1a1a',
      },
      fontFamily: {
        inter: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
