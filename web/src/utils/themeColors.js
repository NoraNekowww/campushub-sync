/**
 * CampusHub 全局主题色系与自定义配色工具库
 */

export const THEME_COLOR_PRESETS = [
  {
    id: 'blue',
    name: '克莱因蓝',
    hex: '#3366ff',
    scale: {
      50: '238 244 255',
      100: '217 230 255',
      200: '188 211 255',
      300: '142 181 255',
      400: '89 140 255',
      500: '51 102 255',
      600: '31 71 230',
      700: '26 55 180',
      800: '27 49 144',
      900: '28 47 116',
    },
  },
  {
    id: 'emerald',
    name: '翡翠薄荷',
    hex: '#10b981',
    scale: {
      50: '236 253 245',
      100: '209 250 229',
      200: '167 243 208',
      300: '110 231 183',
      400: '52 211 153',
      500: '16 185 129',
      600: '5 150 105',
      700: '4 120 87',
      800: '6 95 70',
      900: '6 78 59',
    },
  },
  {
    id: 'violet',
    name: '极光星紫',
    hex: '#8b5cf6',
    scale: {
      50: '245 243 255',
      100: '237 233 254',
      200: '221 214 254',
      300: '196 181 253',
      400: '167 139 250',
      500: '139 92 246',
      600: '124 58 237',
      700: '109 40 217',
      800: '91 33 182',
      900: '76 29 149',
    },
  },
  {
    id: 'amber',
    name: '琥珀暖阳',
    hex: '#f59e0b',
    scale: {
      50: '255 251 235',
      100: '254 243 199',
      200: '253 230 138',
      300: '252 211 77',
      400: '251 191 36',
      500: '245 158 11',
      600: '217 119 6',
      700: '180 83 9',
      800: '146 64 14',
      900: '120 53 15',
    },
  },
  {
    id: 'rose',
    name: '樱花珊瑚',
    hex: '#f43f5e',
    scale: {
      50: '255 241 242',
      100: '255 228 230',
      200: '254 205 211',
      300: '253 164 175',
      400: '251 113 133',
      500: '244 63 94',
      600: '225 29 72',
      700: '190 18 60',
      800: '159 18 57',
      900: '136 19 55',
    },
  },
  {
    id: 'slate',
    name: '石墨深灰',
    hex: '#64748b',
    scale: {
      50: '248 250 252',
      100: '241 245 249',
      200: '226 232 240',
      300: '203 213 225',
      400: '148 163 184',
      500: '100 116 139',
      600: '71 85 105',
      700: '51 65 85',
      800: '30 41 59',
      900: '15 23 42',
    },
  },
]

/**
 * 将 Hex 转为 RGB 数组
 */
function hexToRgb(hex) {
  let clean = String(hex).replace('#', '').trim()
  if (clean.length === 3) {
    clean = clean.split('').map((c) => c + c).join('')
  }
  const num = parseInt(clean, 16)
  if (isNaN(num)) return [51, 102, 255]
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
}

/**
 * 混色算法：根据基准颜色生成从 50 到 900 的色阶
 */
function generateScaleFromHex(hex) {
  const [r, g, b] = hexToRgb(hex)

  const mix = (r1, g1, b1, r2, g2, b2, weight) => {
    const w = Math.max(0, Math.min(1, weight))
    const nr = Math.round(r1 * (1 - w) + r2 * w)
    const ng = Math.round(g1 * (1 - w) + g2 * w)
    const nb = Math.round(b1 * (1 - w) + b2 * w)
    return `${nr} ${ng} ${nb}`
  }

  // 往白色混 (50 ~ 400)
  // 往黑色混 (600 ~ 900)
  return {
    50: mix(r, g, b, 255, 255, 255, 0.94),
    100: mix(r, g, b, 255, 255, 255, 0.84),
    200: mix(r, g, b, 255, 255, 255, 0.68),
    300: mix(r, g, b, 255, 255, 255, 0.48),
    400: mix(r, g, b, 255, 255, 255, 0.24),
    500: `${r} ${g} ${b}`,
    600: mix(r, g, b, 0, 0, 0, 0.15),
    700: mix(r, g, b, 0, 0, 0, 0.32),
    800: mix(r, g, b, 0, 0, 0, 0.52),
    900: mix(r, g, b, 0, 0, 0, 0.72),
  }
}

/**
 * 全局应用主题色并持久化
 */
export function applyThemeColor(colorIdOrHex) {
  if (typeof document === 'undefined') return

  const preset = THEME_COLOR_PRESETS.find((p) => p.id === colorIdOrHex)
  const scale = preset ? preset.scale : generateScaleFromHex(colorIdOrHex)

  const root = document.documentElement
  for (const [level, rgb] of Object.entries(scale)) {
    root.style.setProperty(`--brand-${level}`, rgb)
  }

  try {
    localStorage.setItem('campushub.theme_color', colorIdOrHex)
  } catch (e) {}
}

export function getSavedThemeColor() {
  try {
    return localStorage.getItem('campushub.theme_color') || 'blue'
  } catch (e) {
    return 'blue'
  }
}
