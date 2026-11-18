package online.nzlab.schedule;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.RemoteViews;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class TodayWidgetProvider extends AppWidgetProvider {

    private static final String API_URL = "https://nzlab.online/schedule/api/widgets/today";
    private static final String PREF_NAME = "campushub_auth";
    private static final String KEY_ADMIN_TOKEN = "admin_token";
    private static final String KEY_SESSION_TOKEN = "session_token";
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();
    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());

    public static void requestRefresh(Context context) {
        if (context == null) return;
        AppWidgetManager mgr = AppWidgetManager.getInstance(context);
        int[] ids = mgr.getAppWidgetIds(new ComponentName(context, TodayWidgetProvider.class));
        if (ids != null && ids.length > 0) {
            Intent intent = new Intent(context, TodayWidgetProvider.class);
            intent.setAction(AppWidgetManager.ACTION_APPWIDGET_UPDATE);
            intent.putExtra(AppWidgetManager.EXTRA_APPWIDGET_IDS, ids);
            context.sendBroadcast(intent);
        }
    }

    @Override
    public void onUpdate(Context context, AppWidgetManager appWidgetManager, int[] appWidgetIds) {
        for (int appWidgetId : appWidgetIds) {
            updateAppWidget(context, appWidgetManager, appWidgetId);
        }
        // 异步后台拉取今日最新日程数据更新桌面小部件
        fetchLatestTodayData(context);
    }

    static void updateAppWidget(Context context, AppWidgetManager appWidgetManager, int appWidgetId) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_today);

        SimpleDateFormat timeFormat = new SimpleDateFormat("HH:mm", Locale.CHINA);
        timeFormat.setTimeZone(TimeZone.getTimeZone("Asia/Shanghai"));
        views.setTextViewText(R.id.widgetClock, timeFormat.format(new Date()));

        // 点击小部件任意区域直接启动主应用
        Intent intent = new Intent(context, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        views.setOnClickPendingIntent(R.id.widgetRoot, pendingIntent);
        views.setOnClickPendingIntent(R.id.heroCard, pendingIntent);

        appWidgetManager.updateAppWidget(appWidgetId, views);
    }

    private void fetchLatestTodayData(Context context) {
        EXECUTOR.execute(() -> {
            try {
                SharedPreferences prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
                String adminToken = prefs.getString(KEY_ADMIN_TOKEN, "").trim();
                String sessionToken = prefs.getString(KEY_SESSION_TOKEN, "").trim();

                String reqUrl = API_URL;
                if (!adminToken.isEmpty()) {
                    reqUrl = API_URL + "?token=" + URLEncoder.encode(adminToken, "UTF-8");
                }

                URL url = new URL(reqUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(6000);
                conn.setReadTimeout(6000);
                if (!adminToken.isEmpty()) {
                    conn.setRequestProperty("X-Admin-Token", adminToken);
                }
                if (!sessionToken.isEmpty()) {
                    conn.setRequestProperty("X-Session-Token", sessionToken);
                }

                int code = conn.getResponseCode();
                if (code == 200) {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        sb.append(line);
                    }
                    reader.close();

                    JSONObject data = new JSONObject(sb.toString());
                    MAIN_HANDLER.post(() -> renderWidgetData(context, data));
                } else if (code == 401 || code == 403) {
                    MAIN_HANDLER.post(() -> renderAuthHint(context));
                }
            } catch (Exception ignored) {
                // 网络不通时保持最后一次渲染或默认视图
            }
        });
    }

    private static void renderAuthHint(Context context) {
        AppWidgetManager appWidgetManager = AppWidgetManager.getInstance(context);
        ComponentName thisWidget = new ComponentName(context, TodayWidgetProvider.class);
        int[] allWidgetIds = appWidgetManager.getAppWidgetIds(thisWidget);
        if (allWidgetIds == null || allWidgetIds.length == 0) return;

        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_today);
        views.setViewVisibility(R.id.heroCard, View.GONE);
        int[] rowIds = { R.id.itemRow1, R.id.itemRow2, R.id.itemRow3, R.id.itemRow4 };
        for (int rowId : rowIds) {
            views.setViewVisibility(rowId, View.GONE);
        }
        views.setViewVisibility(R.id.emptyNotice, View.VISIBLE);
        views.setTextViewText(R.id.emptyNotice, "请先打开 CampusHub 登录账号后同步课表");
        views.setTextViewText(R.id.widgetSummary, "点击进入 CampusHub 登录");

        for (int widgetId : allWidgetIds) {
            appWidgetManager.updateAppWidget(widgetId, views);
        }
    }

    private static void renderWidgetData(Context context, JSONObject data) {
        AppWidgetManager appWidgetManager = AppWidgetManager.getInstance(context);
        ComponentName thisWidget = new ComponentName(context, TodayWidgetProvider.class);
        int[] allWidgetIds = appWidgetManager.getAppWidgetIds(thisWidget);
        if (allWidgetIds == null || allWidgetIds.length == 0) return;

        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_today);

        String dateLabel = data.optString("date_label", "今日日程");
        int totalClasses = data.optInt("total_classes", 0);
        int totalDeadlines = data.optInt("total_deadlines", 0);
        String currentTime = data.optString("current_time", "");

        if (!currentTime.isEmpty()) {
            views.setTextViewText(R.id.widgetClock, currentTime);
        }
        views.setTextViewText(R.id.widgetTitle, dateLabel + " · " + totalClasses + " 节 · " + totalDeadlines + " DDL");

        // 1. 处理 Hero 焦点卡片（正在上课或即将开始的下一节课）
        JSONObject hero = data.optJSONObject("current_class");
        boolean isNow = true;
        if (hero == null) {
            hero = data.optJSONObject("next_class");
            isNow = false;
        }

        String heroId = "";
        if (hero != null) {
            heroId = hero.optString("id", "");
            views.setViewVisibility(R.id.heroCard, View.VISIBLE);
            views.setTextViewText(R.id.heroStatus, isNow ? "正在进行" : "下一项");
            views.setTextViewText(R.id.heroClassTitle, hero.optString("title", "未知日程"));
            views.setTextViewText(R.id.heroClassTime, hero.optString("time", ""));
            String loc = hero.optString("location", "").trim();
            if (!loc.isEmpty()) {
                views.setTextViewText(R.id.heroLocation, loc);
                views.setViewVisibility(R.id.heroLocation, View.VISIBLE);
            } else {
                views.setViewVisibility(R.id.heroLocation, View.GONE);
            }
        } else {
            views.setViewVisibility(R.id.heroCard, View.GONE);
        }

        // 2. 解析所有今日日程
        List<JSONObject> scheduleItems = new ArrayList<>();
        JSONArray allItemsJson = data.optJSONArray("all_items");
        if (allItemsJson != null && allItemsJson.length() > 0) {
            for (int i = 0; i < allItemsJson.length(); i++) {
                JSONObject item = allItemsJson.optJSONObject(i);
                if (item != null) {
                    scheduleItems.add(item);
                }
            }
        } else {
            JSONArray classes = data.optJSONArray("classes");
            if (classes != null) {
                for (int i = 0; i < classes.length(); i++) {
                    JSONObject c = classes.optJSONObject(i);
                    if (c != null) {
                        try {
                            JSONObject item = new JSONObject(c.toString());
                            item.put("type", "class");
                            scheduleItems.add(item);
                        } catch (Exception ignored) {}
                    }
                }
            }
            JSONArray deadlines = data.optJSONArray("deadlines");
            if (deadlines != null) {
                for (int i = 0; i < deadlines.length(); i++) {
                    JSONObject d = deadlines.optJSONObject(i);
                    if (d != null) {
                        try {
                            JSONObject item = new JSONObject(d.toString());
                            item.put("type", "deadline");
                            item.put("start_time", d.optString("time", ""));
                            scheduleItems.add(item);
                        } catch (Exception ignored) {}
                    }
                }
            }
            Collections.sort(scheduleItems, new Comparator<JSONObject>() {
                @Override
                public int compare(JSONObject a, JSONObject b) {
                    String sa = a.optString("start_time", a.optString("time", ""));
                    String sb = b.optString("start_time", b.optString("time", ""));
                    return sa.compareTo(sb);
                }
            });
        }

        // 优先展示未结束的活动日程与待办（过滤已在 Hero 展示的条目）
        List<JSONObject> activeItems = new ArrayList<>();
        List<JSONObject> pastItems = new ArrayList<>();
        for (JSONObject it : scheduleItems) {
            String itemId = it.optString("id", "");
            if (!heroId.isEmpty() && heroId.equals(itemId)) {
                continue;
            }
            if ("past".equals(it.optString("status", ""))) {
                pastItems.add(it);
            } else {
                activeItems.add(it);
            }
        }
        List<JSONObject> listItems = new ArrayList<>(activeItems);
        if (listItems.isEmpty() && hero == null) {
            listItems.addAll(pastItems);
        }

        // 3. 填充多日程槽位（Slot 1 ~ 4）
        int[] rowIds = { R.id.itemRow1, R.id.itemRow2, R.id.itemRow3, R.id.itemRow4 };
        int[] tagIds = { R.id.itemTag1, R.id.itemTag2, R.id.itemTag3, R.id.itemTag4 };
        int[] timeIds = { R.id.itemTime1, R.id.itemTime2, R.id.itemTime3, R.id.itemTime4 };
        int[] titleIds = { R.id.itemTitle1, R.id.itemTitle2, R.id.itemTitle3, R.id.itemTitle4 };
        int[] locIds = { R.id.itemLoc1, R.id.itemLoc2, R.id.itemLoc3, R.id.itemLoc4 };

        int displayCount = Math.min(listItems.size(), 4);
        int textNormal = context.getColor(R.color.widget_title);
        int textMuted = context.getColor(R.color.widget_text_muted);

        for (int i = 0; i < 4; i++) {
            if (i < displayCount) {
                JSONObject item = listItems.get(i);
                views.setViewVisibility(rowIds[i], View.VISIBLE);

                String type = item.optString("type", "class");
                String status = item.optString("status", "");
                boolean isOngoing = "ongoing".equals(status);
                boolean isPast = "past".equals(status);

                if (isOngoing) {
                    views.setTextViewText(tagIds[i], "进行中");
                    views.setInt(tagIds[i], "setBackgroundResource", R.drawable.widget_tag_now);
                    views.setTextColor(tagIds[i], context.getColor(R.color.widget_tag_now_text));
                } else if ("deadline".equals(type)) {
                    views.setTextViewText(tagIds[i], "DDL");
                    views.setInt(tagIds[i], "setBackgroundResource", R.drawable.widget_tag_todo);
                    views.setTextColor(tagIds[i], context.getColor(R.color.widget_tag_todo_text));
                } else {
                    views.setTextViewText(tagIds[i], "日程");
                    views.setInt(tagIds[i], "setBackgroundResource", R.drawable.widget_tag_class);
                    views.setTextColor(tagIds[i], context.getColor(R.color.widget_tag_class_text));
                }

                views.setTextViewText(timeIds[i], item.optString("time", ""));
                views.setTextViewText(titleIds[i], item.optString("title", ""));
                views.setTextColor(titleIds[i], isPast ? textMuted : textNormal);

                String loc = item.optString("location", "").trim();
                if (!loc.isEmpty()) {
                    views.setTextViewText(locIds[i], loc);
                    views.setViewVisibility(locIds[i], View.VISIBLE);
                } else {
                    views.setViewVisibility(locIds[i], View.GONE);
                }
            } else {
                views.setViewVisibility(rowIds[i], View.GONE);
            }
        }

        // 4. 空状态控制
        if (hero == null && displayCount == 0) {
            views.setViewVisibility(R.id.emptyNotice, View.VISIBLE);
            if (totalClasses == 0 && totalDeadlines == 0) {
                views.setTextViewText(R.id.emptyNotice, "今天没有待办和课程，好好休息吧~");
            } else {
                views.setTextViewText(R.id.emptyNotice, "今日课程与待办已全部完成");
            }
        } else {
            views.setViewVisibility(R.id.emptyNotice, View.GONE);
        }

        // 5. 底部汇总文案
        if (listItems.size() > 4) {
            int more = listItems.size() - 4;
            views.setTextViewText(R.id.widgetSummary, "还有 " + more + " 项日程 · 点击进入完整课表");
        } else {
            views.setTextViewText(R.id.widgetSummary, "点击进入完整课表");
        }

        Intent intent = new Intent(context, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        views.setOnClickPendingIntent(R.id.widgetRoot, pendingIntent);
        views.setOnClickPendingIntent(R.id.heroCard, pendingIntent);
        for (int rowId : rowIds) {
            views.setOnClickPendingIntent(rowId, pendingIntent);
        }

        for (int widgetId : allWidgetIds) {
            appWidgetManager.updateAppWidget(widgetId, views);
        }
    }
}
