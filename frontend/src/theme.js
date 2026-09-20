const KEY = 'sundial-theme'

export const THEMES = ['light', 'dark']

export function initialTheme() {
  const saved = localStorage.getItem(KEY)
  if (THEMES.includes(saved)) return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme
}

export function rememberTheme(theme) {
  localStorage.setItem(KEY, theme)
}
