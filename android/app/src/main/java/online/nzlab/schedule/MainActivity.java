package online.nzlab.schedule;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import java.io.InputStream;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "CampusHub";
    private static final String APP_URL = "https://nzlab.online/schedule/";
    private static final String PREF_NAME = "campushub_auth";
    private static final String KEY_ADMIN_TOKEN = "admin_token";

    private WebView webView;
    private SwipeRefreshLayout swipeRefresh;
    private SharedPreferences prefs;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 沉浸式深色状态栏与导航栏，消除启动白屏闪烁
        setupImmersiveDarkBars();

        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        swipeRefresh = findViewById(R.id.swipeRefresh);
        webView = findViewById(R.id.webView);

        // 彻底根治登录态丢失：启用 CookieManager 并配置强持久化
        setupCookiePersistence();

        // 极致性能调优：硬件加速与本地缓存
        webView.setBackgroundColor(Color.parseColor("#0b1220"));
        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        // 本地化与秒开体验：优先加载本地离线缓存（LOAD_CACHE_ELSE_NETWORK）
        settings.setCacheMode(WebSettings.LOAD_CACHE_ELSE_NETWORK);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setSupportZoom(false);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(settings.getUserAgentString() + " CampusHubAndroid/1.0");

        // 注入原生桥接接口，用于本地凭据双重兜底
        webView.addJavascriptInterface(new AuthBridge(), "NativeAuthBridge");

        // 极速秒开架构：静态资源本地 0 延迟秒开拦截，API 走网络
        webView.setWebViewClient(new FastLocalWebViewClient());

        // 注入 WebChromeClient：优化渲染管道与控制台日志
        webView.setWebChromeClient(new WebChromeClient());

        // 进一步提速：允许后台线程优先渲染
        webView.getSettings().setRenderPriority(WebSettings.RenderPriority.HIGH);

        // 下拉刷新
        swipeRefresh.setColorSchemeColors(Color.parseColor("#2563eb"));
        swipeRefresh.setProgressBackgroundColorSchemeColor(Color.parseColor("#1e293b"));
        swipeRefresh.setOnRefreshListener(() -> {
            CookieManager.getInstance().flush();
            webView.reload();
        });

        // 监听系统后退手势
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (webView != null && webView.canGoBack()) {
                    webView.goBack();
                } else {
                    setEnabled(false);
                    getOnBackPressedDispatcher().onBackPressed();
                }
            }
        });

        // 加载主应用（本地秒开拦截，0 网络等待）
        webView.loadUrl(APP_URL);
    }

    private void setupCookiePersistence() {
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, true);
        cookieManager.flush();
    }

    private void setupImmersiveDarkBars() {
        Window window = getWindow();
        window.clearFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS);
        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        window.setStatusBarColor(Color.parseColor("#0b1220"));
        window.setNavigationBarColor(Color.parseColor("#0b1220"));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(true);
        }
    }

    /**
     * 极速启动客户端：
     * 静态前端代码（HTML, JS, CSS, 图标）直接从本地 assets/web/ 秒开读取，0 毫秒网络延迟！
     * 动态 API 请求（/schedule/api/*）正常穿透走网络。
     */
    private class FastLocalWebViewClient extends WebViewClient {

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            String path = uri.getPath();

            // 如果是 API 请求，放行给网络
            if (path != null && path.contains("/api/")) {
                return null;
            }

            // 拦截静态资源，直接从本地 assets/web 闪存秒开
            if (path != null) {
                String subPath = null;
                if (path.startsWith("/schedule/")) {
                    subPath = path.substring("/schedule/".length());
                } else if (path.equals("/") || path.startsWith("/assets/") || path.startsWith("/icons/")) {
                    subPath = path.startsWith("/") ? path.substring(1) : path;
                }

                if (subPath != null) {
                    if (subPath.isEmpty() || subPath.equals("index.html")) {
                        return getAssetResponse("web/index.html", "text/html");
                    }
                    if (subPath.startsWith("assets/")) {
                        String mime = subPath.endsWith(".js") ? "application/javascript" :
                                     subPath.endsWith(".css") ? "text/css" : "application/octet-stream";
                        return getAssetResponse("web/" + subPath, mime);
                    }
                    if (subPath.startsWith("icons/")) {
                        return getAssetResponse("web/" + subPath, "image/png");
                    }
                    if (subPath.equals("manifest.webmanifest")) {
                        return getAssetResponse("web/manifest.webmanifest", "application/manifest+json");
                    }
                    if (subPath.equals("widget.html")) {
                        return getAssetResponse("web/widget.html", "text/html");
                    }
                    if (subPath.startsWith("widgets/")) {
                        return getAssetResponse("web/" + subPath, "application/json");
                    }
                }
            }

            return null;
        }

        private WebResourceResponse getAssetResponse(String assetPath, String mimeType) {
            try {
                AssetManager am = getAssets();
                InputStream is = am.open(assetPath);
                return new WebResourceResponse(mimeType, "UTF-8", is);
            } catch (Exception e) {
                return null;
            }
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            swipeRefresh.setRefreshing(false);

            // 强制将内存 Cookie 写入磁盘 SQLite 数据库，避免被系统清理
            CookieManager.getInstance().flush();

            // 双重保险：检查 SharedPreferences 中是否有备份 Token，自动注入还原
            String backupToken = prefs.getString(KEY_ADMIN_TOKEN, "");
            if (!backupToken.isEmpty()) {
                String injectScript = "(function() {" +
                        "  try {" +
                        "    if (!localStorage.getItem('campushub.adminToken')) {" +
                        "      localStorage.setItem('campushub.adminToken', '" + backupToken + "');" +
                        "    }" +
                        "  } catch(e) {}" +
                        "})();";
                view.evaluateJavascript(injectScript, null);
            }

            // 监听前端当前的 Token 并备份到原生 SharedPreferences
            String backupScript = "(function() {" +
                    "  try {" +
                    "    var t = localStorage.getItem('campushub.adminToken') || '';" +
                    "    if (window.NativeAuthBridge) { window.NativeAuthBridge.syncToken(t); }" +
                    "  } catch(e) {}" +
                    "})();";
            view.evaluateJavascript(backupScript, null);
        }
    }

    public class AuthBridge {
        @JavascriptInterface
        public void syncToken(String token) {
            if (token != null && !token.isEmpty()) {
                prefs.edit().putString(KEY_ADMIN_TOKEN, token).apply();
            }
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        // 退出或切后台时，确保 Cookie 完整落盘保存
        CookieManager.getInstance().flush();
        if (webView != null) {
            webView.onPause();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onDestroy() {
        CookieManager.getInstance().flush();
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
