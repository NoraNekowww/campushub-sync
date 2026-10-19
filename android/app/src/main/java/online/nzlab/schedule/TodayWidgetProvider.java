package online.nzlab.schedule;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
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
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class TodayWidgetProvider extends AppWidgetProvider {

    private static final String API_URL = "https://nzlab.online/schedule/api/widgets/today";
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();
    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());

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

        SimpleDateFormat timeFormat = new SimpleDateFormat("HH:mm", Locale.getDefault());
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
                URL url = new URL(API_URL);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");
                conn.setConnectTimeout(6000);
                conn.setReadTimeout(6000);

                if (conn.getResponseCode() == 200) {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        sb.append(line);
                    }
                    reader.close();

                    JSONObject data = new JSONObject(sb.toString());
                    MAIN_HANDLER.post(() -> renderWidgetData(context, data));
                }
            } catch (Exception ignored) {
                // 网络不通时保持最后一次渲染或默认视图
            }
        });
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
        views.setTextViewText(R.id.widgetTitle, "CampusHub · " + dateLabel);

        JSONObject hero = data.optJSONObject("current_class");
        boolean isNow = true;
        if (hero == null) {
            hero = data.optJSONObject("next_class");
            isNow = false;
        }

        if (hero != null) {
            views.setViewVisibility(R.id.heroCard, View.VISIBLE);
            views.setTextViewText(R.id.heroStatus, isNow ? "正在上课" : "下一节课");
            views.setTextViewText(R.id.heroClassTitle, hero.optString("title", "未知课程"));
            views.setTextViewText(R.id.heroClassTime, hero.optString("time", ""));
            String loc = hero.optString("location", "").trim();
            if (!loc.isEmpty()) {
                views.setTextViewText(R.id.heroLocation, "📍 " + loc);
                views.setViewVisibility(R.id.heroLocation, View.VISIBLE);
            } else {
                views.setViewVisibility(R.id.heroLocation, View.GONE);
            }
        } else {
            views.setViewVisibility(R.id.heroCard, View.VISIBLE);
            views.setTextViewText(R.id.heroStatus, "今日日程");
            views.setTextViewText(R.id.heroClassTitle, totalClasses == 0 ? "今天没有课程安排" : "今日课程已全部结束");
            views.setTextViewText(R.id.heroClassTime, "共 " + totalClasses + " 节课 · " + totalDeadlines + " 个待办");
            views.setViewVisibility(R.id.heroLocation, View.GONE);
        }

        views.setTextViewText(R.id.widgetSummary, "点击进入完整课表 · 左右无极滑动");

        Intent intent = new Intent(context, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        views.setOnClickPendingIntent(R.id.widgetRoot, pendingIntent);
        views.setOnClickPendingIntent(R.id.heroCard, pendingIntent);

        for (int widgetId : allWidgetIds) {
            appWidgetManager.updateAppWidget(widgetId, views);
        }
    }
}
