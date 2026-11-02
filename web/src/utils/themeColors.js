/**
 * CampusHub 全局主题色系与自定义配色工具库
 * 采用温润、低饱和度、莫兰迪雅致色彩规范，护眼舒适耐看
 */

export const THEME_COLOR_PRESETS = [
  {
    id: 'blue',
    name: '静谧灰蓝',
    hex: '#4a6fa5',
    scale: {
      50: '243 246 251',
      100: '228 235 245',
      200: '206 218 236',
      300: '172 192 222',
      400: '128 156 198',
      500: '74 111 165',
      600: '61 92 139',
      700: '50 74 113',
      800: '43 62 93',
      900: '37 53 78',
    },
  },
  {
    id: 'emerald',
    name: '鼠尾草绿',
    hex: '#4e8775',
    scale: {
      50: '242 248 245',
      100: '226 239 233',
      200: '202 224 214',
      300: '166 202 187',
      400: '123 172 153',
      500: '78 135 117',
      600: '62 110 95',
      700: '51 89 77',
      800: '43 73 64',
      900: '37 61 54',
    },
  },
  {
    id: 'violet',
    name: '丁香灰紫',
    hex: '#76689a',
    scale: {
      50: '246 245 249',
      100: '235 233 242',
      200: '218 214 230',
      300: '192 186 212',
      400: '158 149 187',
      500: '118 104 154',
      600: '99 86 131',
      700: '82 71 109',
      800: '68 59 90',
      900: '58 51 76',
    },
  },
  {
    id: 'amber',
    name: '暖栗秋橙',
    hex: '#a0704d',
    scale: {
      50: '250 246 242',
      100: '244 235 226',
      200: '233 217 200',
      300: '216 191 164',
      400: '193 158 123',
      500: '160 112 77',
      600: '138 94 62',
      700: '113 76 51',
      800: '93 63 43',
      900: '77 53 38',
    },
  },
  {
    id: 'rose',
    name: '烟粉豆沙',
    hex: '#a26171',
    scale: {
      50: '251 245 246',
      100: '245 233 236',
      200: '235 214 220',
      300: '220 186 196',
      400: '199 149 163',
      500: '162 97 113',
      600: '139 79 93',
      700: '115 64 76',
      800: '95 54 64',
      900: '79 46 54',
    },
  },
  {
    id: 'slate',
    name: '石墨冷灰',
    hex: '#5e6b7c',
    scale: {
      50: '246 247 249',
      100: '236 238 242',
      200: '218 222 229',
      300: '192 198 209',
      400: '154 163 178',
      500: '94 107 124',
      600: '78 89 104',
      700: '65 74 87',
      800: '54 62 72',
      900: '45 52 61',
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
  if (isNaN(num)) return [74, 111, 165]
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
}

/**
 * 混色算法：根据基准颜色生成从 50 到 900 的柔和低饱和色阶
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

  return {
    50: mix(r, g, b, 255, 255, 255, 0.93),
    100: mix(r, g, b, 255, 255, 255, 0.82),
    200: mix(r, g, b, 255, 255, 255, 0.65),
    300: mix(r, g, b, 255, 255, 255, 0.44),
    400: mix(r, g, b, 255, 255, 255, 0.22),
    500: `${r} ${g} ${b}`,
    600: mix(r, g, b, 0, 0, 0, 0.16),
    700: mix(r, g, b, 0, 0, 0, 0.33),
    800: mix(r, g, b, 0, 0, 0, 0.52),
    900: mix(r, g, b, 0, 0, 0, 0.70),
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
