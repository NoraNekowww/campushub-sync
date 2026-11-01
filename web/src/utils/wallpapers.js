/**
 * 高质感图床与壁纸分类精选库 (按分类索引与真随机加载)
 * 严格挑选真正的深空天文摄影（韦伯/哈勃望远镜、星系、深空星云、月海、星轨）、自然旷野、建筑光影与极简微光
 * 每一项均配对高质量的浅色模式 (Light) 与深色模式 (Dark) 摄影作品
 */
export const WALLPAPER_CATEGORIES = [
  {
    key: 'astronomy',
    name: '深空天文摄影',
    desc: '韦伯/哈勃望远镜深空星系、发射星云、超新星遗迹与星轨',
    items: [
      {
        title: '宇宙深场与微光星系',
        light: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1462331940025-496dfbfc7564?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '船底座大星云与创生之柱',
        light: 'https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '银河悬臂与地平线极光',
        light: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1509198397868-475647b2a1e5?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '暗夜星轨与猎户座大星云',
        light: 'https://images.unsplash.com/photo-1447433589675-4aaa569f3e05?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1543722530-d2c3201371e7?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '月球地貌与深空星芒',
        light: 'https://images.unsplash.com/photo-1532693322450-2cb5c511067d?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1502134249126-9f3755a50d78?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
  {
    key: 'nature',
    name: '自然风光与雪原',
    desc: '高耸雪峰、晨曦云海、冰川孤峰与静谧旷野',
    items: [
      {
        title: '阿尔卑斯雪山晨雾',
        light: 'https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '静谧湖泊与松林雪霁',
        light: 'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1472214103451-9374bd1c798e?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '挪威峡湾与极地落日',
        light: 'https://images.unsplash.com/photo-1434725039720-aaad6dd32dfe?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '冰岛黑沙滩与狂澜海潮',
        light: 'https://images.unsplash.com/photo-1518837695005-2083093ee35b?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1498050108023-c5249f4df085?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
  {
    key: 'city',
    name: '城市光影与建筑',
    desc: '现代主义建筑线条、晨光天际线与夜幕流光',
    items: [
      {
        title: '包豪斯几何白与赛博夜幕',
        light: 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1519501025264-65ba15a82390?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '极简清水混凝土与幕墙倒影',
        light: 'https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1508873696983-2df5703bc20d?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '维多利亚港晨光与都市霓虹',
        light: 'https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1514565131-fce0801e5785?auto=format&fit=crop&w=1920&q=85',
      },
    ],
  },
  {
    key: 'minimal',
    name: '极简流光与抽象',
    desc: '低饱和雅致微光、纯净渐变流体与次表面折射',
    items: [
      {
        title: '流体微光波纹',
        light: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '纯净微晶折射与暗夜微粒',
        light: 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?auto=format&fit=crop&w=1920&q=85',
        dark: 'https://images.unsplash.com/photo-1550684376-efcbd6e3f031?auto=format&fit=crop&w=1920&q=85',
      },
      {
        title: '空气感薄雾与微芒晨辉',
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

  // 排除当前已显示的项
  const candidates = pool.filter((it) => it.light !== currentLightUrl)
  const source = candidates.length > 0 ? candidates : pool
  const idx = Math.floor(Math.random() * source.length)
  return source[idx]
}
