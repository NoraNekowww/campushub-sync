<template>
  <div class="space-y-4 px-4">
    <!-- ======================================================= 一级菜单首页 -->
    <template v-if="!activeSubpage">
      <!-- 未导入课表的新用户才展示两步接入引导；一旦成功导入课表立即自动隐藏 -->
      <section
        v-if="!hasImportedTimetable"
        class="card space-y-3 p-4"
        data-testid="onboarding-section"
      >
        <header class="flex items-center gap-2">
          <Sparkles :size="15" class="text-brand-600 dark:text-brand-400" />
          <h2 class="text-sm font-semibold">两步接入你自己的账号</h2>
        </header>
        <p class="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
          每个账号的数据互相隔离：课表、待办、自定义日程保存在服务器数据库中，并支持本机离线秒开。
        </p>
        <ol class="space-y-2.5 text-xs">
          <li v-for="step in onboarding" :key="step.key" class="flex items-start gap-2">
            <span
              class="mt-1 h-2 w-2 shrink-0 rounded-full"
              :class="step.done ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-600'"
            />
            <div class="min-w-0 flex-1">
              <p class="font-medium">{{ step.title }}</p>
              <p class="text-[11px] text-slate-500 dark:text-slate-400">{{ step.hint }}</p>
            </div>
            <button
              v-if="step.subpage"
              type="button"
              class="btn-ghost shrink-0 !py-1 text-[11px]"
              @click="enterSubpage(step.subpage)"
            >
              {{ step.done ? '查看' : '去设置' }}
            </button>
          </li>
        </ol>
      </section>

      <!-- 二级菜单导航入口列表 -->
      <section class="card divide-y divide-slate-100 overflow-hidden dark:divide-slate-800/80" data-testid="settings-menu">
        <button
          v-for="item in menuItems"
          :key="item.key"
          type="button"
          :data-testid="`settings-nav-${item.key}`"
          class="flex w-full items-center gap-3.5 px-4 py-3.5 text-left transition-colors hover:bg-slate-50/80 active:bg-slate-100/80 dark:hover:bg-slate-800/50 dark:active:bg-slate-800/80"
          @click="enterSubpage(item.key)"
        >
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
            :class="item.iconBg"
          >
            <component :is="item.icon" :size="18" :class="item.iconColor" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-slate-800 dark:text-slate-100">{{ item.title }}</span>
              <span
                v-if="item.badge"
                class="chip border-transparent !px-2 !py-0 text-[10px]"
                :class="item.badgeClass"
              >
                {{ item.badge }}
              </span>
            </div>
            <p class="mt-0.5 truncate text-[11px] text-slate-500 dark:text-slate-400">
              {{ item.desc }}
            </p>
          </div>
          <ChevronRight :size="16" class="shrink-0 text-slate-400 dark:text-slate-500" />
        </button>
      </section>

      <!-- 一级底部版本与反馈信息 -->
      <footer class="pb-1 pt-1 text-center text-[11px] leading-relaxed text-slate-400">
        <div class="mb-1 text-[11px] text-slate-400 dark:text-slate-500">
          {{ isAndroidClient ? 'CampusHub Android' : (cfg.app || 'CampusHub Sync') }} v{{ clientAppVersion }}
          <span v-if="lastUpdatedLabel"> · 数据更新于 {{ lastUpdatedLabel }}</span>
        </div>
        <a
          href="https://github.com/NoraNekowww/campushub-sync/issues/new"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1 underline decoration-dotted underline-offset-2 transition hover:text-slate-200"
          data-testid="issue-link"
        >
          <CircleAlert :size="12" />
          遇到问题 / 想提建议？去 GitHub 提 Issue
        </a>
      </footer>
    </template>

    <!-- ======================================================= 二级子菜单详情页 -->
    <template v-else>
      <!-- 二级子页面顶部返回导航条 -->
      <div class="flex items-center gap-2 pt-0.5">
        <button
          type="button"
          class="btn-ghost !h-8 !px-2.5 text-xs font-medium"
          data-testid="settings-subpage-back"
          @click="leaveSubpage"
        >
          <ArrowLeft :size="14" />
          <span>返回设置</span>
        </button>
        <h2 class="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {{ activeSubpageTitle }}
        </h2>
      </div>

      <!-- --------------------------------- 子页 1：课表与教务导入 -->
      <template v-if="activeSubpage === 'timetable'">
        <section class="card space-y-3 p-4">
          <header class="flex items-center gap-2">
            <GraduationCap :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">天津大学课表</h3>
            <span class="chip ml-auto border-transparent bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300">
              {{ tju.mode || '—' }}
            </span>
          </header>

          <DetailList
            :data="semester"
            :labels="{ name: '学期', start_date: '第一周周一', total_weeks: '周数', week: '当前周', holidays: '假期' }"
          />

          <TjuConnect id="tju-section" :tju="tju" :semester="semester" />

          <div class="space-y-2 border-t border-slate-100 pt-3 dark:border-slate-800">
            <p class="label">学期设置</p>
            <div class="grid grid-cols-2 gap-2">
              <input v-model="semesterForm.name" class="input text-xs" placeholder="学期名称" />
              <input v-model="semesterForm.start_date" class="input text-xs" type="date" />
              <input v-model.number="semesterForm.total_weeks" class="input text-xs" type="number" min="1" max="30" placeholder="总周数" />
              <button class="btn-primary text-xs" :disabled="busy" @click="saveSemester">保存学期</button>
            </div>
          </div>
        </section>
      </template>

      <!-- --------------------------------- 子页 2：外观与壁纸 -->
      <template v-else-if="activeSubpage === 'appearance'">
        <section class="card space-y-4 p-4" data-testid="appearance-section">
          <header class="flex items-center gap-2">
            <Palette :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">外观与个性化</h3>
          </header>

          <!-- 主题配色 -->
          <div class="space-y-2 pb-1">
            <div class="flex items-center justify-between">
              <label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <Palette :size="13" class="text-brand-500" />
                <span>主题配色</span>
              </label>
              <span class="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                {{ currentThemeColorName }}
              </span>
            </div>

            <div class="grid grid-cols-3 sm:grid-cols-6 gap-2">
              <button
                v-for="color in THEME_COLOR_PRESETS"
                :key="color.id"
                type="button"
                class="flex items-center gap-1.5 rounded-lg border p-2 text-xs font-medium transition"
                :class="
                  state.themeColor === color.id
                    ? 'border-brand-500 bg-brand-50/70 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300 font-semibold shadow-xs'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300'
                "
                @click="setThemeColor(color.id)"
              >
                <span
                  class="h-3.5 w-3.5 rounded-full shrink-0 shadow-2xs border border-black/10 dark:border-white/10"
                  :style="{ backgroundColor: color.hex }"
                />
                <span class="truncate">{{ color.name }}</span>
              </button>
            </div>

            <div class="flex items-center gap-2.5 pt-0.5">
              <label class="flex items-center gap-2 cursor-pointer text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200">
                <input
                  type="color"
                  :value="customColorHex"
                  class="h-5 w-6 cursor-pointer rounded border border-slate-300 bg-transparent p-0 dark:border-slate-700"
                  title="自由选择任意主色调"
                  @input="onCustomColorInput($event.target.value)"
                />
                <span>自由拾色器</span>
              </label>
              <span v-if="isCustomThemeColor" class="font-mono text-xs text-brand-600 dark:text-brand-400 font-medium">
                {{ state.themeColor }}
              </span>
            </div>
          </div>

          <!-- 自定义背景图与本地持久化壁纸缓存 -->
          <div class="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800">
            <div class="flex items-center justify-between">
              <label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <ImageIcon :size="13" class="text-indigo-500" />
                <span>自定义背景图与本地缓存图床</span>
              </label>
              <button
                type="button"
                class="chip border-transparent text-[10px] py-0.5 cursor-pointer"
                :class="
                  bgForm.enabled
                    ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300 font-semibold'
                    : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                "
                @click="toggleBgEnabled"
              >
                {{ bgForm.enabled ? '已开启' : '点击开启' }}
              </button>
            </div>

            <div v-if="bgForm.enabled" class="space-y-3 rounded-xl border border-slate-200/70 bg-slate-50/60 p-3 text-xs dark:border-slate-800 dark:bg-slate-800/40">
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-slate-700 dark:text-slate-300 text-[11px]">壁纸分类选择（自动缓存至本机）</span>
                  <button
                    type="button"
                    class="btn-primary !h-7 !py-0 !px-2.5 text-[11px] gap-1 shadow-xs"
                    @click="randomizeWallpaper()"
                  >
                    <Shuffle :size="12" />
                    <span>随机换一张</span>
                  </button>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                  <button
                    v-for="cat in wallpaperCategories"
                    :key="cat.key"
                    type="button"
                    class="flex flex-col items-start rounded-lg border p-2 text-left transition"
                    :class="
                      bgForm.category === cat.key
                        ? 'border-brand-500 bg-brand-50/70 text-brand-900 dark:bg-brand-500/20 dark:text-brand-100 font-semibold shadow-2xs'
                        : 'border-slate-200 bg-white hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'
                    "
                    @click="selectWallpaperCategory(cat.key)"
                  >
                    <span class="text-[11px]">{{ cat.name }}</span>
                    <span class="text-[9px] text-slate-400 font-normal line-clamp-1 mt-0.5">{{ cat.desc }}</span>
                  </button>
                </div>

                <div v-if="bgForm.wallpaperTitle" class="flex items-center gap-1.5 text-[10px] text-slate-400 pt-0.5">
                  <span class="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                  <span>当前壁纸：<strong>{{ bgForm.wallpaperTitle }}</strong>（已缓存，进入即显）</span>
                </div>
              </div>

              <div class="space-y-2 pt-1 border-t border-slate-200/60 dark:border-slate-700/60">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-slate-700 dark:text-slate-300 text-[11px]">从相册/本地选择自定义背景图</span>
                  <button
                    type="button"
                    class="btn-secondary !h-7 !py-0 !px-2.5 text-[11px] gap-1 shadow-2xs"
                    @click="triggerCustomBgUpload()"
                  >
                    <Upload :size="12" />
                    <span>上传本地壁纸</span>
                  </button>
                </div>
                <input
                  ref="customBgFileInput"
                  type="file"
                  accept="image/*"
                  class="hidden"
                  @change="onCustomBgFileSelected"
                />
              </div>

              <div class="space-y-1 pt-1 border-t border-slate-200/60 dark:border-slate-700/60">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-slate-700 dark:text-slate-300 text-[11px]">浅色主题背景图 (Light Mode)</span>
                  <span v-if="!state.isDarkTheme" class="chip border-transparent bg-brand-50 text-brand-600 text-[9px] py-0">当前生效</span>
                </div>
                <input
                  v-model="bgForm.lightUrl"
                  type="url"
                  placeholder="输入浅色模式背景图直链 URL..."
                  class="input !py-1 text-xs"
                  @change="updateBgConfig"
                />
              </div>

              <div class="space-y-1">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-slate-700 dark:text-slate-300 text-[11px]">深色主题背景图 (Dark Mode)</span>
                  <span v-if="state.isDarkTheme" class="chip border-transparent bg-indigo-50 text-indigo-600 text-[9px] py-0">当前生效</span>
                </div>
                <input
                  v-model="bgForm.darkUrl"
                  type="url"
                  placeholder="输入深色模式背景图直链 URL..."
                  class="input !py-1 text-xs"
                  @change="updateBgConfig"
                />
              </div>

              <div class="grid grid-cols-2 gap-3 pt-1 border-t border-slate-200/60 dark:border-slate-700/60">
                <div class="space-y-1">
                  <div class="flex items-center justify-between text-[11px] text-slate-600 dark:text-slate-400">
                    <span>背景不透明度</span>
                    <span class="font-mono text-[10px]">{{ bgForm.opacity }}%</span>
                  </div>
                  <input
                    v-model.number="bgForm.opacity"
                    type="range"
                    min="10"
                    max="90"
                    step="5"
                    class="w-full accent-brand-600"
                    @input="updateBgConfig"
                  />
                </div>
                <div class="space-y-1">
                  <div class="flex items-center justify-between text-[11px] text-slate-600 dark:text-slate-400">
                    <span>非课表页模糊度</span>
                    <span class="font-mono text-[10px]">{{ bgForm.blur }}px</span>
                  </div>
                  <input
                    v-model.number="bgForm.blur"
                    type="range"
                    min="0"
                    max="16"
                    step="1"
                    class="w-full accent-brand-600"
                    @input="updateBgConfig"
                  />
                </div>
              </div>

              <div class="flex items-center justify-between pt-1 border-t border-slate-200/60 dark:border-slate-700/60">
                <span class="text-[10px] text-slate-400">课表页默认启用全屏高斯模糊呈现</span>
                <button
                  type="button"
                  class="chip border-transparent text-rose-500 hover:underline text-[10px] py-0.5 ml-auto"
                  @click="resetBgConfig"
                >
                  重置并清空壁纸
                </button>
              </div>
            </div>
          </div>

          <!-- 默认课表列显示模式 -->
          <div class="space-y-2 border-t border-slate-100 pt-3 dark:border-slate-800" data-testid="week-anchor-section">
            <div class="flex items-center justify-between">
              <label class="flex items-center gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
                <CalendarDays :size="13" class="text-brand-500" />
                <span>默认课表显示模式</span>
              </label>
              <span class="text-[10px] text-slate-400">可滑动拓展 0:00–24:00</span>
            </div>
            <div class="grid grid-cols-2 gap-2">
              <button
                type="button"
                data-testid="anchor-monday-first"
                class="flex flex-col items-start rounded-xl border p-2.5 text-left transition"
                :class="
                  state.weekAnchorMode !== 'today_third'
                    ? 'border-brand-500 bg-brand-50/70 text-brand-900 dark:bg-brand-500/20 dark:text-brand-100 font-semibold shadow-xs'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300'
                "
                @click="setWeekAnchorMode('monday_first')"
              >
                <span class="text-xs">本周视图（默认）</span>
                <span class="mt-0.5 text-[10px] font-normal text-slate-500 dark:text-slate-400">
                  固定周一在第一列（周一至周日）
                </span>
              </button>
              <button
                type="button"
                data-testid="anchor-today-third"
                class="flex flex-col items-start rounded-xl border p-2.5 text-left transition"
                :class="
                  state.weekAnchorMode === 'today_third'
                    ? 'border-brand-500 bg-brand-50/70 text-brand-900 dark:bg-brand-500/20 dark:text-brand-100 font-semibold shadow-xs'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300'
                "
                @click="setWeekAnchorMode('today_third')"
              >
                <span class="text-xs">今天在第三列</span>
                <span class="mt-0.5 text-[10px] font-normal text-slate-500 dark:text-slate-400">
                  前天、昨天、今天居第三列，连续浏览
                </span>
              </button>
            </div>
          </div>

          <!-- 课表底色切换 -->
          <div class="space-y-1.5 border-t border-slate-100 pt-3 dark:border-slate-800">
            <label class="text-xs font-semibold text-slate-700 dark:text-slate-300">课表网格线风格</label>
            <div class="grid grid-cols-3 gap-2">
              <button
                type="button"
                class="flex items-center justify-center gap-1 rounded-lg border py-2 text-xs font-medium transition"
                :class="state.weekGridStyle === 'grid' || !state.weekGridStyle ? 'border-brand-500 bg-brand-50/70 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300 font-semibold shadow-sm' : 'border-slate-200 hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300'"
                @click="setWeekGridStyle('grid')"
              >
                <Grid :size="13" />
                <span>标准网格</span>
              </button>
              <button
                type="button"
                class="flex items-center justify-center gap-1 rounded-lg border py-2 text-xs font-medium transition"
                :class="state.weekGridStyle === 'subgrid' ? 'border-brand-500 bg-brand-50/70 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300 font-semibold shadow-sm' : 'border-slate-200 hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300'"
                @click="setWeekGridStyle('subgrid')"
              >
                <Grid :size="13" class="stroke-[2.5]" />
                <span>细分网格</span>
              </button>
              <button
                type="button"
                class="flex items-center justify-center gap-1 rounded-lg border py-2 text-xs font-medium transition"
                :class="state.weekGridStyle === 'blank' ? 'border-brand-500 bg-brand-50/70 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300 font-semibold shadow-sm' : 'border-slate-200 hover:border-slate-300 text-slate-700 dark:border-slate-700 dark:text-slate-300'"
                @click="setWeekGridStyle('blank')"
              >
                <Square :size="13" />
                <span>空白底</span>
              </button>
            </div>
          </div>

          <!-- 主题模式切换 -->
          <div class="space-y-1.5 border-t border-slate-100 pt-3 dark:border-slate-800">
            <label class="text-xs font-semibold text-slate-700 dark:text-slate-300">主题模式</label>
            <div class="flex gap-2">
              <button
                v-for="mode in themes"
                :key="mode.value"
                class="chip"
                :class="state.theme === mode.value ? 'chip-active' : 'chip-idle'"
                @click="setTheme(mode.value)"
              >
                <component :is="mode.icon" :size="12" />
                {{ mode.label }}
              </button>
            </div>
          </div>
        </section>
      </template>

      <!-- --------------------------------- 子页 3：账号与云同步 -->
      <template v-else-if="activeSubpage === 'account'">
        <section v-if="state.offlineMode" class="card space-y-2 p-4" data-testid="offline-account">
          <header class="flex items-center gap-2">
            <UserRound :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">账号</h3>
            <span class="chip border-transparent bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300">
              本地账号
            </span>
          </header>
          <p class="text-xs leading-relaxed text-slate-500 dark:text-slate-400">
            离线模式：课表、日程与待办只保存在这台设备上，不上传服务器，也不做云端同步。
          </p>
          <button
            type="button"
            class="btn-primary !py-1.5 text-xs"
            data-testid="offline-exit"
            @click="exitOffline"
          >
            退出离线模式（登录 / 注册云端账号）
          </button>
        </section>

        <section v-if="accountsEnabled && !state.offlineMode" class="card space-y-3 p-4" data-testid="account-section">
          <header class="flex items-center gap-2">
            <UserRound :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">账号</h3>
            <span
              class="chip border-transparent"
              :class="
                account
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300'
              "
            >
              {{ account ? '已登录' : '未登录' }}
            </span>
            <span
              v-if="account?.is_admin"
              class="chip border-transparent bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300"
            >
              管理员
            </span>
          </header>

          <template v-if="account">
            <dl class="grid grid-cols-3 gap-x-3 gap-y-1 text-xs">
              <dt class="text-slate-500 dark:text-slate-400">用户名</dt>
              <dd class="col-span-2 font-medium" data-testid="account-username">{{ account.username }}</dd>
              <dt class="text-slate-500 dark:text-slate-400">注册时间</dt>
              <dd class="col-span-2">{{ account.created_at_label || '—' }}</dd>
              <dt class="text-slate-500 dark:text-slate-400">上次登录</dt>
              <dd class="col-span-2">{{ account.last_login_label || '—' }}</dd>
            </dl>

            <div class="flex flex-wrap gap-2">
              <button
                class="btn-ghost !py-1.5 text-xs"
                data-testid="account-logout"
                :disabled="state.authBusy"
                @click="signOut"
              >
                退出登录
              </button>
              <button class="btn-ghost !py-1.5 text-xs" @click="showPasswordForm = !showPasswordForm">
                {{ showPasswordForm ? '收起' : '修改密码' }}
              </button>
              <button
                type="button"
                class="btn-ghost !py-1.5 text-xs !text-rose-600 hover:!bg-rose-50 dark:!text-rose-400 dark:hover:!bg-rose-950/30"
                :disabled="state.authBusy"
                data-testid="account-delete-self"
                @click="confirmDeleteAccount"
              >
                注销账号
              </button>
            </div>

            <form v-if="showPasswordForm" class="space-y-2" @submit.prevent="submitPassword()">
              <input
                v-model="passwordForm.current"
                class="input text-xs"
                type="password"
                autocomplete="current-password"
                placeholder="当前密码"
              />
              <input
                v-model="passwordForm.next"
                class="input text-xs"
                type="password"
                autocomplete="new-password"
                :placeholder="`新密码（至少 ${minPasswordLength} 位）`"
              />
              <input
                v-model="passwordForm.confirm"
                class="input text-xs"
                type="password"
                autocomplete="new-password"
                placeholder="确认新密码"
              />
              <button class="btn-primary !py-1.5 text-xs" type="submit" :disabled="state.authBusy">
                保存新密码
              </button>
            </form>

            <div v-if="isAdminUser" class="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-700">
              <header class="flex items-center gap-2">
                <Users :size="14" class="text-slate-500" />
                <h4 class="text-xs font-semibold">成员（{{ members.length }}）</h4>
                <button class="btn-ghost !py-1 text-[11px]" :disabled="membersBusy" @click="loadMembers">
                  <RefreshCw :size="12" /> 刷新
                </button>
              </header>
              <ul class="space-y-1 text-xs">
                <li
                  v-for="row in members"
                  :key="row.id"
                  class="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-2 py-1.5 dark:bg-slate-800/60"
                >
                  <span class="truncate">
                    {{ row.username }}
                    <span v-if="row.is_admin" class="text-brand-600 dark:text-brand-400">· 管理员</span>
                    <span v-if="!row.is_active" class="text-rose-500">· 已停用</span>
                  </span>
                  <button
                    v-if="row.id !== account.id"
                    class="btn-ghost !py-1 text-[11px]"
                    @click="toggleMember(row)"
                  >
                    {{ row.is_active ? '停用' : '启用' }}
                  </button>
                </li>
              </ul>
            </div>
          </template>

          <template v-else>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              这个日程表需要账号才能读取。登录后本机自动保持登录状态，日历订阅链接不受影响。
            </p>
            <button class="btn-primary !py-1.5 text-xs" @click="openAuthGate()">
              <LogIn :size="13" /> 登录 / 注册
            </button>
          </template>
        </section>

        <!-- 管理员专区：注册与验证 -->
        <section v-if="isAdminUser" class="card space-y-3 p-4" data-testid="registration-section">
          <header class="flex flex-wrap items-center gap-2">
            <ShieldCheck :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">注册与验证</h3>
            <span
              class="chip"
              :class="
                registration.registration_open
                  ? 'border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                  : 'border-transparent bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
              "
            >
              {{ registration.registration_open ? '开放注册' : '已关闭' }}
            </span>
          </header>

          <div class="space-y-2 rounded-xl bg-slate-50 p-2.5 text-xs dark:bg-slate-800/60">
            <div class="flex items-center gap-2">
              <span class="shrink-0 text-slate-500 dark:text-slate-400">当前邀请码</span>
              <code class="min-w-0 flex-1 truncate font-mono text-[13px]">{{
                registration.invite_code || '（未设置）'
              }}</code>
              <button class="btn-ghost shrink-0 !py-1 text-[11px]" @click="copyInvite">
                <Copy :size="12" /> 复制
              </button>
              <button
                class="btn-ghost shrink-0 !py-1 text-[11px]"
                :disabled="registrationBusy"
                @click="rotateInvite"
              >
                <RefreshCw :size="12" /> 换一个
              </button>
            </div>

            <label class="flex items-center gap-2">
              <input
                type="checkbox"
                :checked="registration.invite_required"
                :disabled="registrationBusy"
                @change="saveRegistration({ invite_required: $event.target.checked })"
              />
              <span>注册必须填邀请码（关掉即只靠验证码）</span>
            </label>

            <label class="flex items-center gap-2">
              <input
                type="checkbox"
                :checked="registration.captcha_enabled"
                :disabled="registrationBusy"
                @change="saveRegistration({ captcha_enabled: $event.target.checked })"
              />
              <span>注册必须过图形验证码</span>
            </label>

            <div class="flex items-center gap-2 pt-0.5">
              <input
                v-model="inviteDraft"
                class="input min-w-0 flex-1 text-xs"
                placeholder="自定义邀请码（留空不改动）"
                @keyup.enter="inviteDraft.trim() && saveRegistration({ invite_code: inviteDraft })"
              />
              <button
                class="btn-primary shrink-0 !py-1.5 text-xs"
                :disabled="registrationBusy || !inviteDraft.trim()"
                @click="saveRegistration({ invite_code: inviteDraft })"
              >
                保存
              </button>
            </div>
          </div>

          <p class="text-[11px] text-slate-500 dark:text-slate-400">
            把
            <code class="rounded bg-slate-100 px-1 font-mono dark:bg-slate-800">{{ registerLink }}</code>
            发给同学，让他们注册用自己的账号登录（各自的课表和待办互不可见）。
          </p>
        </section>

        <!-- 管理员专区：用户存储监控 -->
        <section v-if="isAdminUser" class="card space-y-3 p-4" data-testid="storage-monitor-section">
          <header class="flex flex-wrap items-center gap-2">
            <HardDrive :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">用户存储占用与空间监控</h3>
            <span class="chip border-transparent bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
              {{ storageStats?.total_physical_formatted || '0 KB' }}
            </span>
            <div class="ml-auto flex items-center gap-2">
              <button
                class="btn-ghost !py-1 text-[11px]"
                :disabled="storageBusy"
                title="刷新存储状态"
                @click="loadStorageStats"
              >
                <RefreshCw :size="12" :class="storageBusy ? 'animate-spin' : ''" /> 刷新
              </button>
              <button
                class="btn-primary !py-1 text-[11px]"
                :disabled="storageBusy"
                title="将 WAL 刷盘并执行 VACUUM 回收磁盘碎片"
                @click="runOptimizeStorage"
              >
                优化与压缩存储
              </button>
            </div>
          </header>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead>
                <tr class="border-b border-slate-100 text-[11px] font-semibold text-slate-400 dark:border-slate-800">
                  <th class="pb-1.5 font-normal">用户</th>
                  <th class="pb-1.5 font-normal text-right">课程</th>
                  <th class="pb-1.5 font-normal text-right">待办</th>
                  <th class="pb-1.5 font-normal text-right">总日程</th>
                  <th class="pb-1.5 font-normal text-right">估算占用</th>
                  <th class="pb-1.5 font-normal pl-3">空间占比</th>
                  <th class="pb-1.5 font-normal text-right pr-1">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100/60 dark:divide-slate-800/40">
                <tr v-for="user in storageStats?.users || []" :key="user.id" class="text-slate-700 dark:text-slate-300">
                  <td class="py-2 font-medium">
                    {{ user.username }}
                    <span v-if="user.role === 'admin'" class="text-[10px] text-brand-600 dark:text-brand-400">· 管理员</span>
                    <span v-if="!user.is_active" class="text-[10px] text-rose-500">· 已停用</span>
                  </td>
                  <td class="py-2 text-right font-mono text-slate-500 dark:text-slate-400">{{ user.class_count }}</td>
                  <td class="py-2 text-right font-mono font-medium text-amber-600 dark:text-amber-400">{{ user.deadline_count }}</td>
                  <td class="py-2 text-right font-mono font-semibold">{{ user.total_events }}</td>
                  <td class="py-2 text-right font-mono text-slate-500 dark:text-slate-400">{{ user.storage_est_formatted }}</td>
                  <td class="py-2 pl-3">
                    <div class="flex items-center gap-1.5">
                      <div class="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                        <div
                          class="h-full rounded-full bg-brand-500"
                          :style="{ width: `${Math.min(100, user.storage_percent || 0)}%` }"
                        />
                      </div>
                      <span class="text-[10px] font-mono text-slate-400">{{ user.storage_percent }}%</span>
                    </div>
                  </td>
                  <td class="py-2 text-right pr-1">
                    <button
                      v-if="user.id !== state.user?.id"
                      type="button"
                      class="btn-ghost !py-0.5 !px-2 text-[11px] text-rose-500 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-500/10"
                      @click="confirmDeleteUser(user)"
                    >
                      移除账号
                    </button>
                    <span v-else class="text-[10px] text-slate-400">当前账号</span>
                  </td>
                </tr>
                <tr v-if="!(storageStats?.users || []).length">
                  <td colspan="7" class="py-3 text-center text-slate-400">暂无用户数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>

      <!-- --------------------------------- 子页 4：日历订阅与导出 -->
      <template v-else-if="activeSubpage === 'calendar'">
        <section class="card space-y-3 p-4">
          <header class="flex items-center gap-2">
            <CalendarPlus :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">日历订阅 (.ics)</h3>
          </header>
          <p class="text-xs text-slate-500 dark:text-slate-400">
            在 iOS 日历 / Android 的「通过 URL 添加日历」里粘贴下面的地址，截止时间与课程会自动同步（含 15 分钟提醒）。
          </p>
          <div v-if="subscribeUrl" class="space-y-3">
            <textarea
              class="input h-20 resize-none break-all font-mono text-[11px]"
              readonly
              :value="subscribeUrl"
            />
            <div class="flex flex-wrap gap-2">
              <button class="btn-primary !py-1.5 text-xs" @click="copy(subscribeUrl, '订阅地址已复制')">
                <Copy :size="13" /> 复制地址
              </button>
              <a class="btn-ghost !py-1.5 text-xs" :href="webcalUrl">
                <CalendarPlus :size="13" /> 直接订阅
              </a>
              <button class="btn-ghost !py-1.5 text-xs" @click="copy(prettyUrl, 'HTTPS 地址已复制')">
                复制 https 版本
              </button>
              <a
                class="btn-ghost !py-1.5 text-xs inline-flex items-center gap-1 text-brand-600 dark:text-brand-400 font-medium"
                :href="prettyUrl"
                download="campushub.ics"
              >
                <Download :size="13" /> 下载 .ics 文件
              </a>
            </div>
            <p v-if="!subscribeConfigured" class="text-[11px] text-amber-600 dark:text-amber-400">
              后端未配置 <code>SUBSCRIBE_TOKEN</code>，部署到公网前请务必设置。
            </p>

            <div class="rounded-xl border border-slate-200/80 bg-slate-50/70 p-3 text-xs space-y-2.5 dark:border-slate-800 dark:bg-slate-800/40">
              <div class="flex items-center gap-1.5 font-semibold text-slate-800 dark:text-slate-200">
                <Smartphone :size="14" class="text-brand-600 dark:text-brand-400" />
                <span>系统日历导入与邮件同步（免 URL 链接订阅方案）</span>
              </div>
              <div class="rounded-lg border border-slate-200/60 bg-white/70 p-2.5 space-y-1.5 dark:border-slate-700/60 dark:bg-slate-900/40">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-slate-700 dark:text-slate-300">方式 A：本地文件直接导入</span>
                  <a
                    class="btn-primary !py-1 text-xs"
                    :href="prettyUrl"
                    download="campushub.ics"
                  >
                    <Download :size="12" /> 下载日历文件
                  </a>
                </div>
                <p class="text-[10.5px] text-slate-400 dark:text-slate-500">
                  下载后点击打开 <code>campushub.ics</code>，手机自带日历即可识别并导入全学期课程与日程。
                </p>
              </div>

              <div class="rounded-lg border border-slate-200/60 bg-white/70 p-2.5 space-y-2 dark:border-slate-700/60 dark:bg-slate-900/40">
                <span class="block font-medium text-slate-700 dark:text-slate-300">方式 B：通过邮箱日历导入</span>
                <div class="flex gap-2">
                  <input
                    v-model="recipientEmail"
                    type="email"
                    placeholder="输入接收邮箱地址..."
                    class="input !py-1 text-xs flex-1"
                    :disabled="sendingEmail"
                  />
                  <button
                    class="btn-primary !py-1 text-xs shrink-0"
                    :disabled="!recipientEmail || sendingEmail"
                    @click="sendCalendarEmail"
                  >
                    <Mail v-if="!sendingEmail" :size="12" />
                    <RefreshCw v-else :size="12" class="animate-spin" />
                    <span>{{ sendingEmail ? '发送中...' : '发送至邮箱' }}</span>
                  </button>
                </div>
                <p v-if="emailStatus" class="text-[10.5px]" :class="emailStatusOk ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">
                  {{ emailStatus }}
                </p>
              </div>
            </div>
          </div>
          <p v-else class="text-xs text-slate-400">未获取到订阅地址（离线模式或未登录云端账号时不支持生成在线订阅链接）。</p>
        </section>
      </template>

      <!-- --------------------------------- 子页 5：版本更新与数据维护 -->
      <template v-else-if="activeSubpage === 'system'">
        <section class="card space-y-3 p-4" data-testid="update-section">
          <header class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <Rocket :size="15" class="text-brand-600 dark:text-brand-400" />
              <h3 class="text-sm font-semibold">软件版本与在线更新</h3>
            </div>
            <span class="chip border-transparent bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 font-mono text-[10px]">
              v{{ appVersionDisplay }}
            </span>
          </header>

          <div class="rounded-xl border border-slate-200/80 bg-slate-50/60 p-3 text-xs dark:border-slate-800 dark:bg-slate-800/40 space-y-2.5">
            <div class="flex items-center justify-between">
              <div class="space-y-0.5">
                <div class="font-medium text-slate-800 dark:text-slate-200">
                  {{ updateCheckStatus || '保持最新可获得最流畅体验' }}
                </div>
                <p v-if="latestReleaseInfo" class="text-[11px] text-slate-500 dark:text-slate-400">
                  最新版本：<strong>v{{ latestReleaseInfo.version }}</strong>
                </p>
              </div>
              <button
                type="button"
                class="btn-secondary !h-8 !py-0 !px-3 text-xs gap-1.5 shadow-2xs shrink-0"
                :disabled="checkingUpdate"
                @click="manualCheckUpdate"
              >
                <RotateCcw :size="12" :class="checkingUpdate ? 'animate-spin' : ''" />
                <span>{{ checkingUpdate ? '检查中...' : '检查更新' }}</span>
              </button>
            </div>

            <div
              v-if="hasNewVersion"
              class="rounded-lg border border-brand-200/80 bg-brand-50/60 p-2.5 space-y-2 dark:border-brand-500/30 dark:bg-brand-950/30 animate-fade-in"
            >
              <div class="flex items-center gap-1.5 font-semibold text-brand-700 dark:text-brand-300 text-xs">
                <Sparkles :size="13" />
                <span>发现新版本 v{{ latestReleaseInfo?.version }}</span>
              </div>
              <p v-if="latestReleaseInfo?.features?.length" class="text-[11px] text-slate-600 dark:text-slate-300 space-y-0.5">
                <span v-for="(feat, idx) in latestReleaseInfo.features" :key="idx" class="block">
                  · {{ feat }}
                </span>
              </p>
              <div class="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  class="btn-primary !h-8 !py-0 !px-3 text-xs gap-1.5 shadow-sm"
                  @click="downloadAndInstall"
                >
                  <Download :size="13" />
                  <span>直接在应用内下载安装</span>
                </button>
              </div>
            </div>

            <div class="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-200/60 dark:border-slate-700/50">
              <a
                href="https://nzlab.online/schedule/CampusHub.apk"
                download="CampusHub.apk"
                class="btn-primary !h-7 !py-0 !px-2.5 text-[11px] gap-1 shadow-2xs inline-flex items-center"
                data-testid="download-apk-btn"
              >
                <Download :size="12" />
                <span>下载安装包 (APK)</span>
              </a>
              <a
                href="https://github.com/NoraNekowww/campushub-sync/releases/latest"
                target="_blank"
                rel="noopener noreferrer"
                class="btn-ghost !h-7 !py-0 !px-2 text-[11px] inline-flex items-center gap-1 text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              >
                <ExternalLink :size="11" />
                <span>查看 Release 记录</span>
              </a>
            </div>
          </div>
        </section>

        <section class="card space-y-3 p-4">
          <header class="flex items-center gap-2">
            <HardDrive :size="15" class="text-brand-600 dark:text-brand-400" />
            <h3 class="text-sm font-semibold">数据维护与杂项</h3>
          </header>

          <p class="text-xs text-slate-500 dark:text-slate-400">
            时间线、壁纸与课表数据均持久化缓存在本机；如遇异常或需彻底重置，可在此一键清理。
          </p>

          <div class="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
            <button class="btn-ghost !py-1.5 text-xs text-rose-500 hover:text-rose-600" @click="clearCache">
              <Trash2 :size="13" /> 清空所有本地数据与缓存
            </button>
            <span class="text-[11px] text-slate-400">
              {{ isAndroidClient ? 'CampusHub Android' : (cfg.app || 'CampusHub Sync') }} v{{ clientAppVersion }}
              <span v-if="cfg.demo_mode"> · demo</span>
              <span v-if="lastUpdatedLabel"> · 数据更新于 {{ lastUpdatedLabel }}</span>
            </span>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  ArrowLeft,
  CalendarDays,
  CalendarPlus,
  ChevronRight,
  CircleAlert,
  Copy,
  Download,
  ExternalLink,
  GraduationCap,
  Grid,
  HardDrive,
  Image as ImageIcon,
  LogIn,
  Mail,
  Monitor,
  Moon,
  Palette,
  RefreshCw,
  Rocket,
  RotateCcw,
  ShieldCheck,
  Shuffle,
  Smartphone,
  Sparkles,
  Square,
  Sun,
  Trash2,
  Upload,
  UserRound,
  Users,
} from 'lucide-vue-next'
import { api } from '../api'
import DetailList from '../components/DetailList.vue'
import TjuConnect from '../components/TjuConnect.vue'
import { THEME_COLOR_PRESETS } from '../utils/themeColors'
import { WALLPAPER_CATEGORIES, getRandomWallpaper } from '../utils/wallpapers'
import {
  changePassword,
  clearAllLocalData,
  deleteMyAccount,
  disableOfflineMode,
  listUsers,
  loadConfig,
  loadRegistrationSettings,
  logout,
  notify,
  openAuthGate,
  runSync,
  saveBackgroundConfig,
  saveLocalSemester,
  saveRegistrationSettings,
  setTheme,
  setThemeColor,
  setUserActive,
  setWeekAnchorMode,
  setWeekGridStyle,
  state,
} from '../store'

/* ----------------------------------------------------------- 二级菜单导航状态 */
const activeSubpage = computed(() => state.settingsSubpage || null)

function enterSubpage(key) {
  state.settingsSubpage = key
  if (typeof window !== 'undefined') {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function leaveSubpage() {
  state.settingsSubpage = null
}

watch(
  () => state.view,
  (next, prev) => {
    if (prev === 'settings' && next !== 'settings') {
      state.settingsSubpage = null
    }
  },
)

const cfg = computed(() => state.config || {})
const tju = computed(() => cfg.value.tju_schedule || {})
const semester = computed(() => tju.value.semester || {})

const importedCourseCount = computed(() => {
  const metaCount = Number(tju.value?.import_meta?.courses) || 0
  if (metaCount > 0) return metaCount
  const titles = new Set(
    (state.events || [])
      .filter((ev) => !ev.hidden && ev.source === 'tju_schedule')
      .map((ev) => ev.title),
  )
  if (titles.size > 0) return titles.size
  const statusCount = Number(state.status?.counts?.by_source?.tju_schedule) || 0
  return statusCount
})

const hasImportedTimetable = computed(() => importedCourseCount.value > 0)

/* ----------------------------------------------------------- 主题配色响应式与拾色逻辑 */
const currentThemeColorName = computed(() => {
  const p = THEME_COLOR_PRESETS.find((c) => c.id === state.themeColor)
  if (p) return p.name
  return `自定义 (${state.themeColor})`
})

const isCustomThemeColor = computed(() => !THEME_COLOR_PRESETS.some((c) => c.id === state.themeColor))

const customColorHex = computed(() => {
  const p = THEME_COLOR_PRESETS.find((c) => c.id === state.themeColor)
  return p ? p.hex : state.themeColor?.startsWith('#') ? state.themeColor : '#3366ff'
})

function onCustomColorInput(hex) {
  if (hex) setThemeColor(hex)
}

/** 客户端运行版本号 */
const clientAppVersion = computed(() => {
  if (typeof window !== 'undefined' && window.NativeAuthBridge?.getAppVersion) {
    try {
      const v = window.NativeAuthBridge.getAppVersion()
      if (v) return String(v).trim().replace(/^v/i, '')
    } catch (e) {}
  }
  return '3.0.3'
})

const appVersionDisplay = clientAppVersion

const account = computed(() => state.user || null)
const accountsEnabled = computed(() => Boolean(state.accounts?.enabled))

const menuItems = computed(() => [
  {
    key: 'timetable',
    title: '课表与教务导入',
    desc: '天大教务手机直连导入、本地 .ics 导入与学期首周校准',
    badge: hasImportedTimetable.value ? `已导入 ${importedCourseCount.value} 门` : '未导入',
    badgeClass: hasImportedTimetable.value
      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
      : 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
    icon: GraduationCap,
    iconBg: 'bg-brand-50 dark:bg-brand-500/15',
    iconColor: 'text-brand-600 dark:text-brand-400',
  },
  {
    key: 'appearance',
    title: '外观与壁纸',
    desc: `${currentThemeColorName.value} · ${state.weekAnchorMode === 'today_third' ? '今天在第三列' : '本周视图'} · ${bgForm.enabled ? (bgForm.wallpaperTitle || '自定义壁纸') : '纯净底色'}`,
    badge: '',
    badgeClass: '',
    icon: Palette,
    iconBg: 'bg-indigo-50 dark:bg-indigo-500/15',
    iconColor: 'text-indigo-600 dark:text-indigo-400',
  },
  {
    key: 'account',
    title: '账号与云同步',
    desc: state.offlineMode
      ? '当前为离线模式（数据仅保存在本机，可随时切换登录云端）'
      : account.value
        ? `已登录云端账号：${account.value.username}${isAdminUser.value ? ' · 含管理面板' : ''}`
        : '登录或注册云端账号，多端实时同步日程',
    badge: state.offlineMode ? '本地模式' : account.value ? '已登录' : '未登录',
    badgeClass: state.offlineMode
      ? 'bg-slate-100 text-slate-600 dark:bg-slate-700/70 dark:text-slate-300'
      : account.value
        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
        : 'bg-slate-100 text-slate-600 dark:bg-slate-700/70 dark:text-slate-300',
    icon: UserRound,
    iconBg: 'bg-sky-50 dark:bg-sky-500/15',
    iconColor: 'text-sky-600 dark:text-sky-400',
  },
  {
    key: 'calendar',
    title: '日历订阅与导出',
    desc: '生成 .ics 订阅链接、下载日历文件或发送至邮箱导入手机系统日历',
    badge: subscribeUrl.value ? '可用' : '',
    badgeClass: 'bg-brand-50 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300',
    icon: CalendarPlus,
    iconBg: 'bg-emerald-50 dark:bg-emerald-500/15',
    iconColor: 'text-emerald-600 dark:text-emerald-400',
  },
  {
    key: 'system',
    title: '版本更新与数据维护',
    desc: '在线检查更新、下载 APK 安装包、清理本地数据缓存',
    badge: `v${appVersionDisplay.value}`,
    badgeClass: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 font-mono',
    icon: Rocket,
    iconBg: 'bg-amber-50 dark:bg-amber-500/15',
    iconColor: 'text-amber-600 dark:text-amber-400',
  },
])

const activeSubpageTitle = computed(() => {
  const found = menuItems.value.find((m) => m.key === activeSubpage.value)
  return found ? found.title : '系统设置'
})

/* ----------------------------------------------------------- 手动检查更新与下载安装逻辑 */
const checkingUpdate = ref(false)
const updateCheckStatus = ref('')
const latestReleaseInfo = ref(null)

const hasNewVersion = computed(() => {
  if (!latestReleaseInfo.value?.version) return false
  return isNewerVersion(latestReleaseInfo.value.version, clientAppVersion.value)
})

function isNewerVersion(latest, current) {
  if (!latest || !current) return false
  const cleanL = String(latest).trim().replace(/^v/i, '')
  const cleanC = String(current).trim().replace(/^v/i, '')
  if (cleanL === cleanC) return false
  const parse = (v) => v.split('.').map((n) => parseInt(n, 10) || 0)
  const l = parse(cleanL)
  const c = parse(cleanC)
  const maxLen = Math.max(l.length, c.length)
  for (let i = 0; i < maxLen; i++) {
    const lv = l[i] ?? 0
    const cv = c[i] ?? 0
    if (lv > cv) return true
    if (lv < cv) return false
  }
  return false
}

async function manualCheckUpdate() {
  checkingUpdate.value = true
  updateCheckStatus.value = '正在查询最新版本发布...'
  try {
    let version = ''
    let title = ''
    let downloadUrl = ''
    let features = []

    try {
      const vData = await api.appVersion()
      if (vData?.version) {
        version = String(vData.version).replace(/^v/i, '')
        title = vData.title || ''
        downloadUrl = vData.download_url || vData.github_download_url || ''
        features = vData.features || []
      }
    } catch (e) {}

    if (!version) {
      const resp = await fetch(`https://api.github.com/repos/NoraNekowww/campushub-sync/releases/latest?_t=${Date.now()}`, {
        cache: 'no-store',
        headers: { Accept: 'application/vnd.github.v3+json' },
      })
      if (resp.ok) {
        const data = await resp.json()
        version = (data.tag_name || '').replace(/^v/i, '')
        title = data.name || ''
        const apkAsset = data.assets?.find((a) => a.name === 'CampusHub.apk')
        downloadUrl = apkAsset?.browser_download_url || ''
      }
    }

    if (!version) {
      updateCheckStatus.value = '未检测到版本信息，请稍后再试'
      notify('检测版本异常，请检查网络连接', 'warn')
      return
    }

    latestReleaseInfo.value = {
      version,
      title,
      downloadUrl: downloadUrl || 'https://nzlab.online/schedule/CampusHub.apk',
      features,
    }

    if (isNewerVersion(version, clientAppVersion.value)) {
      updateCheckStatus.value = `发现新版本 v${version}`
      notify(`发现新版本 v${version}，可立即下载安装！`, 'ok')
    } else {
      updateCheckStatus.value = `当前已是最新版本 (v${clientAppVersion.value})`
      notify(`当前已是最新版本 (v${clientAppVersion.value})`, 'ok')
    }
  } catch (err) {
    updateCheckStatus.value = '检查更新失败，请稍后重试'
    notify('检查更新失败：' + (err.message || '网络连接超时'), 'danger')
  } finally {
    checkingUpdate.value = false
  }
}

function downloadAndInstall() {
  const targetUrl = latestReleaseInfo.value?.downloadUrl || 'https://nzlab.online/schedule/CampusHub.apk'
  if (typeof window !== 'undefined' && window.NativeAuthBridge?.downloadAndInstallApk) {
    try {
      window.NativeAuthBridge.downloadAndInstallApk(targetUrl)
      notify('已调起后台极速下载，完成后将自动拉起安装', 'ok')
      return
    } catch (e) {
      console.warn('Native download failed:', e)
    }
  }
  window.open(targetUrl, '_blank')
}

const isAndroidClient = computed(() => {
  if (typeof window === 'undefined') return false
  return Boolean(
    window.NativeAuthBridge ||
      window.__CAMPUSHUB_CLIENT__ ||
      /CampusHubAndroid/i.test(navigator.userAgent || '') ||
      (/Android/i.test(navigator.userAgent || '') && /wv|WebView/i.test(navigator.userAgent || '')) ||
      (/Android/i.test(navigator.userAgent || '') && window.matchMedia?.('(display-mode: standalone)')?.matches),
  )
})

const subscribeUrl = computed(() => cfg.value.subscribe?.url || '')
const webcalUrl = computed(() => cfg.value.subscribe?.webcal || subscribeUrl.value)
const prettyUrl = computed(() => subscribeUrl.value.replace(/^webcal:/, 'https:'))
const subscribeConfigured = computed(() => Boolean(cfg.value.subscribe?.configured))
const lastUpdatedLabel = computed(() =>
  state.lastUpdated
    ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(state.lastUpdated)
    : '',
)

const themes = [
  { value: 'auto', label: '跟随系统', icon: Monitor },
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
]

const busy = ref(false)

/* ------------------------------------------------------------ 接入向导 */
const onboarding = computed(() => [
  {
    key: 'account',
    title: '① 选择云端账号或离线本机模式',
    hint: state.offlineMode
      ? '当前使用离线本机模式；也可随时切换登录云端账号'
      : state.user
        ? `已登录：${state.user.username}`
        : '前往「账号与云同步」登录或注册账号',
    done: Boolean(state.user) || Boolean(state.offlineMode),
    subpage: 'account',
  },
  {
    key: 'tju',
    title: '② 导入我的天大课表',
    hint: '填一次学号 + 教务密码一键导入，或选择本地 .ics 文件导入',
    done: hasImportedTimetable.value,
    subpage: 'timetable',
  },
])

/* ------------------------------------------------------- registration gate */
const registration = ref({
  invite_code: '',
  invite_required: false,
  captcha_enabled: true,
  registration_open: true,
})
const registrationBusy = ref(false)
const inviteDraft = ref('')
const registerLink = computed(() => `${location.origin}${location.pathname}`)

async function loadRegistration() {
  try {
    const payload = await loadRegistrationSettings()
    if (payload) registration.value = payload
  } catch (error) {}
}

async function saveRegistration(patch) {
  registrationBusy.value = true
  try {
    const next = await saveRegistrationSettings(patch)
    if (next) registration.value = next
    inviteDraft.value = ''
  } catch (error) {
    notify(error.message || '保存失败', 'danger')
  } finally {
    registrationBusy.value = false
  }
}

function rotateInvite() {
  return saveRegistration({ rotate: true })
}

async function copyInvite() {
  try {
    await navigator.clipboard.writeText(registration.value.invite_code || '')
    notify('邀请码已复制', 'ok')
  } catch (error) {
    notify('复制失败，请手动选中', 'warn')
  }
}

const isAdminUser = computed(() => Boolean(state.user?.is_admin) || Boolean(state.viewerAdmin))
const storageStats = ref(null)
const storageBusy = ref(false)

async function loadStorageStats() {
  if (!isAdminUser.value) return
  storageBusy.value = true
  try {
    const res = await api.authStorage()
    if (res?.ok) storageStats.value = res
  } catch (error) {
  } finally {
    storageBusy.value = false
  }
}

watch(
  isAdminUser,
  (on) => {
    if (on) {
      loadRegistration()
      loadStorageStats()
    }
  },
  { immediate: true },
)

const semesterForm = reactive({ name: '', start_date: '', total_weeks: 16 })

onMounted(async () => {
  syncSemesterForm()
  if (isAdminUser.value) loadMembers()
})

watch(semester, () => syncSemesterForm(), { deep: true })

function syncSemesterForm() {
  const summary = semester.value || {}
  semesterForm.name = summary.name || ''
  semesterForm.start_date = summary.start_date || ''
  semesterForm.total_weeks = summary.total_weeks || 16
}

async function copy(text, message) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    notify(message, 'ok')
  } catch (error) {
    notify('复制失败，请手动选择文本', 'warn')
  }
}

const recipientEmail = ref('')
const sendingEmail = ref(false)
const emailStatus = ref('')
const emailStatusOk = ref(false)

async function sendCalendarEmail() {
  const email = recipientEmail.value.trim()
  if (!email || !email.includes('@')) {
    notify('请输入有效的邮箱地址', 'warn')
    return
  }
  sendingEmail.value = true
  emailStatus.value = ''
  try {
    const res = await api('/subscribe/email', {
      method: 'POST',
      body: { email },
    })
    emailStatusOk.value = Boolean(res.ok)
    emailStatus.value = res.message || (res.ok ? '发送成功！请在邮箱查收' : '发送未完成')
    if (res.ok) notify('日历已发送至邮箱', 'ok')
    else notify(res.message || '发送未完成', 'warn')
  } catch (err) {
    emailStatusOk.value = false
    emailStatus.value = err?.message || '发送失败，请检查网络或配置'
    notify('发送失败: ' + (err?.message || '网络错误'), 'danger')
  } finally {
    sendingEmail.value = false
  }
}

/* ----------------------------------------------------------- background config */
const customBgFileInput = ref(null)

function triggerCustomBgUpload() {
  if (customBgFileInput.value) customBgFileInput.value.click()
}

async function onCustomBgFileSelected(event) {
  const file = event.target?.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    notify('请选择有效的图片文件（JPG/PNG/WebP）', 'warn')
    return
  }

  try {
    const reader = new FileReader()
    reader.onload = async (e) => {
      const rawDataUrl = e.target.result
      const img = new Image()
      img.onload = () => {
        const maxW = 1920
        const maxH = 1920
        let w = img.width
        let h = img.height
        if (w > maxW || h > maxH) {
          if (w / h > maxW / maxH) {
            h = Math.round((h * maxW) / w)
            w = maxW
          } else {
            w = Math.round((w * maxH) / h)
            h = maxH
          }
        }
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0, w, h)

        const compressedDataUrl = canvas.toDataURL('image/jpeg', 0.86)
        bgForm.enabled = true
        bgForm.category = 'custom'
        bgForm.lightUrl = compressedDataUrl
        bgForm.darkUrl = compressedDataUrl
        bgForm.wallpaperTitle = file.name.replace(/\.[^/.]+$/, '') || '自定义本地壁纸'

        updateBgConfig()
        notify('已成功应用并缓存自定义壁纸！', 'ok')
        if (customBgFileInput.value) customBgFileInput.value.value = ''
      }
      img.onerror = () => notify('图片解析失败，请尝试其他图片', 'danger')
      img.src = rawDataUrl
    }
    reader.readAsDataURL(file)
  } catch (err) {
    notify('读取图片失败，请检查文件权限', 'danger')
  }
}

const wallpaperCategories = WALLPAPER_CATEGORIES

const bgForm = reactive({
  enabled: Boolean(state.backgroundConfig?.enabled),
  category: state.backgroundConfig?.category || 'astronomy',
  lightUrl: state.backgroundConfig?.lightUrl || '',
  darkUrl: state.backgroundConfig?.darkUrl || '',
  wallpaperTitle: state.backgroundConfig?.wallpaperTitle || '',
  opacity: Number(state.backgroundConfig?.opacity ?? 75),
  blur: Number(state.backgroundConfig?.blur ?? 0),
})

watch(
  () => state.backgroundConfig,
  (val) => {
    if (!val) return
    bgForm.enabled = Boolean(val.enabled)
    bgForm.category = val.category || 'astronomy'
    bgForm.lightUrl = val.lightUrl || ''
    bgForm.darkUrl = val.darkUrl || ''
    bgForm.wallpaperTitle = val.wallpaperTitle || ''
    bgForm.opacity = Number(val.opacity ?? 75)
    bgForm.blur = Number(val.blur ?? 0)
  },
  { deep: true },
)

function updateBgConfig() {
  saveBackgroundConfig({
    enabled: bgForm.enabled,
    category: bgForm.category,
    lightUrl: bgForm.lightUrl.trim(),
    darkUrl: bgForm.darkUrl.trim(),
    wallpaperTitle: bgForm.wallpaperTitle,
    opacity: Number(bgForm.opacity),
    blur: Number(bgForm.blur),
  })
}

function toggleBgEnabled() {
  bgForm.enabled = !bgForm.enabled
  if (bgForm.enabled && (!bgForm.lightUrl || !bgForm.darkUrl)) {
    randomizeWallpaper(bgForm.category || 'astronomy')
    return
  }
  updateBgConfig()
  notify(bgForm.enabled ? '已启用自定义背景图' : '已关闭背景图，恢复纯净底色', 'ok')
}

function selectWallpaperCategory(catKey) {
  bgForm.category = catKey
  randomizeWallpaper(catKey)
}

function randomizeWallpaper(catKey = bgForm.category) {
  bgForm.enabled = true
  const item = getRandomWallpaper(catKey, bgForm.lightUrl)
  if (item) {
    bgForm.lightUrl = item.light
    bgForm.darkUrl = item.dark
    bgForm.wallpaperTitle = item.title
    updateBgConfig()
    notify(`已换壁纸并写入缓存：${item.title}`, 'ok')
  }
}

function resetBgConfig() {
  bgForm.enabled = false
  bgForm.lightUrl = ''
  bgForm.darkUrl = ''
  bgForm.wallpaperTitle = ''
  bgForm.opacity = 75
  bgForm.blur = 0
  updateBgConfig()
  notify('已重置并清空背景图', 'ok')
}

async function saveSemester() {
  if (!semesterForm.start_date) {
    notify('请填写第一周周一的日期', 'warn')
    return
  }
  busy.value = true
  try {
    if (state.offlineMode) {
      saveLocalSemester({
        name: semesterForm.name || null,
        start_date: semesterForm.start_date,
        total_weeks: Number(semesterForm.total_weeks) || 16,
      })
      notify('学期已保存在本机', 'ok')
      return
    }
    const result = await api.putSemester({
      name: semesterForm.name || null,
      start_date: semesterForm.start_date,
      total_weeks: Number(semesterForm.total_weeks) || 16,
      holidays: [],
    })
    notify(result.message || '学期已保存', 'ok')
    await Promise.all([loadConfig(), runSync()])
    syncSemesterForm()
  } catch (error) {
    notify(error.message || '保存失败', 'danger')
  } finally {
    busy.value = false
  }
}

/* -------------------------------------------------------------- account */
const minPasswordLength = computed(() => Number(state.accounts?.password_min_length) || 8)
const showPasswordForm = ref(false)
const members = ref([])
const membersBusy = ref(false)
const passwordForm = reactive({ current: '', next: '', confirm: '' })

async function signOut() {
  await logout()
  showPasswordForm.value = false
  members.value = []
}

async function exitOffline() {
  await disableOfflineMode()
}

async function confirmDeleteAccount() {
  const currentName = account.value?.username || '当前账号'
  if (
    !window.confirm(
      `确定要注销您的账号「${currentName}」吗？\n\n注意：此操作将永久清理您名下的所有课程、待办日程与个人配置，操作不可撤销！`,
    )
  ) {
    return
  }
  try {
    await deleteMyAccount()
  } catch (e) {
    notify(e.message || '注销账号失败', 'danger')
  }
}

async function submitPassword() {
  const { current, next, confirm } = passwordForm
  if (!current || !next) {
    notify('请填写当前密码与新密码', 'warn')
    return
  }
  if (next !== confirm) {
    notify('两次输入的新密码不一致', 'warn')
    return
  }
  if (next.length < minPasswordLength.value) {
    notify(`新密码至少 ${minPasswordLength.value} 位`, 'warn')
    return
  }
  const ok = await changePassword(current, next)
  if (ok) {
    passwordForm.current = ''
    passwordForm.next = ''
    passwordForm.confirm = ''
    showPasswordForm.value = false
  } else {
    notify(state.authError || '修改失败', 'danger')
  }
}

async function loadMembers() {
  if (!isAdminUser.value) return
  membersBusy.value = true
  try {
    members.value = await listUsers()
  } catch (error) {
    notify(error.message || '无法读取成员列表', 'warn')
  } finally {
    membersBusy.value = false
  }
}

async function toggleMember(row) {
  try {
    await setUserActive(row.id, !row.is_active)
    await loadMembers()
  } catch (error) {
    notify(error.message || '操作失败', 'danger')
  }
}

async function runOptimizeStorage() {
  storageBusy.value = true
  try {
    const res = await api.optimizeStorage()
    notify(res.message || '数据库优化完成', 'ok')
    await loadStorageStats()
  } catch (error) {
    notify(error.message || '优化失败', 'danger')
  } finally {
    storageBusy.value = false
  }
}

async function confirmDeleteUser(user) {
  if (!confirm(`确定要彻底移除账号「${user.username}」吗？\n该操作将同时清理该账号的所有课程与待办数据，不可撤销。`)) {
    return
  }
  storageBusy.value = true
  try {
    const res = await api.deleteUser(user.id)
    notify(res?.message || `账号「${user.username}」已移除`, 'ok')
    await loadStorageStats()
  } catch (error) {
    notify(error.message || '移除账号失败', 'danger')
  } finally {
    storageBusy.value = false
  }
}

function clearCache() {
  if (!window.confirm('确定要清空所有本地数据与缓存吗？未同步的离线数据将被清除。')) return
  clearAllLocalData()
  notify('本地数据与缓存已清空', 'info')
}
</script>
