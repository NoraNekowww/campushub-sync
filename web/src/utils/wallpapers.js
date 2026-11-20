/**
 * 高质感图床与壁纸分类精选库 (每张图均经实拍画质与主题内容严格核验)
 * 每一项均配对真实对应的浅色模式 (Light) 与深色模式 (Dark) 摄影作品
 */
export const WALLPAPER_CATEGORIES = [
  {
    key: 'astronomy',
    name: '深空天文与轨道',
    desc: '近地轨道地球、星系旋臂、宇宙星云与月球地貌',
    items: [
      {
        title: '轨道地球与夜色灯火',
        light: 'https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '雪山银河与深空星云',
        light: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1462331940025-496dfbfc7564?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '仙女座星系与银河核心',
        light: 'https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1502134249126-9f3755a50d78?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '月球全貌与环形山特写',
        light: 'https://images.unsplash.com/photo-1532693322450-2cb5c511067d?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1447433589675-4aaa569f3e05?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
  {
    key: 'nature',
    name: '自然山海与风光',
    desc: '晨雾山谷、雪峰湖湾、高地日出与深海波涛',
    items: [
      {
        title: '晨雾松谷与高山湖湾',
        light: 'https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '薄雾山峦与高地日落',
        light: 'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1472214103451-9374bd1c798e?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '金晖草原与静谧海浪',
        light: 'https://images.unsplash.com/photo-1434725039720-aaad6dd32dfe?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1518837695005-2083093ee35b?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
  {
    key: 'city',
    name: '城市天际线与建筑',
    desc: '现代玻璃幕墙、晴空都会天际线与港湾夜色',
    items: [
      {
        title: '现代玻璃幕墙与都会暮街',
        light: 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1519501025264-65ba15a82390?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '晴空天际线与港湾夜灯',
        light: 'https://images.unsplash.com/photo-1514565131-fce0801e5785?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
  {
    key: 'minimal',
    name: '极简流光与抽象',
    desc: '柔和流体渐变、粉彩弥散极光与暗夜哑光纹理',
    items: [
      {
        title: '丝绸流体与微光液滴',
        light: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '粉彩弥散极光与暗夜砂岩',
        light: 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1550684376-efcbd6e3f031?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '青蓝微光与紫罗兰暮色',
        light: 'https://images.unsplash.com/photo-1557683316-973673baf926?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1557682250-33bd709cbe85?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
]

/**
 * 从指定分类中随机抽取一张（或在全部类别中真随机抽取）
 * @param {string} categoryKey 分类 key（'astronomy' | 'nature' | 'city' | 'minimal' | 'all'）
 * @param {string} currentLightUrl 用于排除当前已在显示的壁纸，实现真正换一张
 */
export function getRandomWallpaper(categoryKey = 'astronomy', currentLightUrl = '') {
  let pool = []
  if (!categoryKey || categoryKey === 'all') {
    pool = WALLPAPER_CATEGORIES.flatMap((c) => c.items)
  } else {
    const cat = WALLPAPER_CATEGORIES.find((c) => c.key === categoryKey)
    pool = cat ? cat.items : WALLPAPER_CATEGORIES[0].items
  }

  if (!pool.length) return null

  const candidates = pool.filter((it) => it.light !== currentLightUrl)
  const source = candidates.length > 0 ? candidates : pool
  const idx = Math.floor(Math.random() * source.length)
  return source[idx]
}
