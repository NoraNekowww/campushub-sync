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
import androidx.webkit.WebViewAssetLoader;

import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "CampusHub";
    private static final String APP_URL = "https://appassets.androidplatform.net/schedule/";
    private static final String PREF_NAME = "campushub_auth";
    private static final String KEY_ADMIN_TOKEN = "admin_token";

    private WebView webView;
    private SwipeRefreshLayout swipeRefresh;
    private SharedPreferences prefs;
    private WebViewAssetLoader assetLoader;

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

        // 背景色设为透明并让硬件加速生效，消除深蓝/黑屏过渡层
        webView.setBackgroundColor(Color.TRANSPARENT);
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
        settings.setAllowFileAccessFromFileURLs(true);
        settings.setAllowUniversalAccessFromFileURLs(true);
        settings.setSupportZoom(false);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(settings.getUserAgentString() + " CampusHubAndroid/1.0");

        // 注入原生桥接接口，用于本地凭据双重兜底
        webView.addJavascriptInterface(new AuthBridge(), "NativeAuthBridge");

        // 1. 构建 Google 官方推荐的本地离线资源拦截器 WebViewAssetLoader
        // 将真实物理路径 assets/web/ 映射到本地虚拟域名 https://appassets.androidplatform.net/schedule/
        assetLoader = new WebViewAssetLoader.Builder()
                .setDomain("appassets.androidplatform.net")
                .addPathHandler("/schedule/", new WebViewAssetLoader.PathHandler() {
                    @Override
                    public WebResourceResponse handle(String path) {
                        try {
                            String assetPath = "web/" + (path.isEmpty() ? "index.html" : path);
                            if (path.isEmpty() || path.equals("index.html")) {
                                assetPath = "web/index.html";
                            }
                            String mime = assetPath.endsWith(".html") ? "text/html" :
                                         assetPath.endsWith(".js") ? "application/javascript" :
                                         assetPath.endsWith(".css") ? "text/css" :
                                         assetPath.endsWith(".png") ? "image/png" :
                                         assetPath.endsWith(".json") || assetPath.endsWith(".webmanifest") ? "application/json" :
                                         "application/octet-stream";

                            InputStream is = getAssets().open(assetPath);
                            Map<String, String> headers = new HashMap<>();
                            headers.put("Access-Control-Allow-Origin", "*");
                            headers.put("Cache-Control", "no-cache");
                            return new WebResourceResponse(mime, "UTF-8", 200, "OK", headers, is);
                        } catch (Exception e) {
                            // 针对前端 SPA 路由跳转直接兜底本地 index.html
                            try {
                                InputStream is = getAssets().open("web/index.html");
                                Map<String, String> headers = new HashMap<>();
                                headers.put("Access-Control-Allow-Origin", "*");
                                return new WebResourceResponse("text/html", "UTF-8", 200, "OK", headers, is);
                            } catch (Exception ex) {
                                return null;
                            }
                        }
                    }
                })
                .build();

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
        // 与前端浅色基底 #f8fafc 与纯白顶栏深度契合，消灭黑屏与深蓝屏跳变
        window.setStatusBarColor(Color.parseColor("#f8fafc"));
        window.setNavigationBarColor(Color.parseColor("#ffffff"));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            View decor = window.getDecorView();
            decor.setSystemUiVisibility(decor.getSystemUiVisibility() | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }
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
            // 优先交给 Google 官方标准 WebViewAssetLoader 处理（完美解决 ES Module、CORS 与离线加载）
            if (assetLoader != null) {
                WebResourceResponse response = assetLoader.shouldInterceptRequest(request.getUrl());
                if (response != null) {
                    return response;
                }
            }
            return handleIntercept(request.getUrl());
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
            Uri uri = Uri.parse(url);
            if (assetLoader != null) {
                WebResourceResponse response = assetLoader.shouldInterceptRequest(uri);
                if (response != null) {
                    return response;
                }
            }
            return handleIntercept(uri);
        }

        private WebResourceResponse handleIntercept(Uri uri) {
            if (uri == null) return null;
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

            // 离线终极兜底：针对 html 页面导航请求，一律返回本地打包好的 index.html
            String pathStr = path != null ? path : "";
            if (pathStr.isEmpty() || pathStr.endsWith("/") || pathStr.endsWith(".html") || !pathStr.contains(".")) {
                return getAssetResponse("web/index.html", "text/html");
            }

            return null;
        }

        private WebResourceResponse getAssetResponse(String assetPath, String mimeType) {
            try {
                AssetManager am = getAssets();
                InputStream is = am.open(assetPath);
                Map<String, String> headers = new HashMap<>();
                headers.put("Access-Control-Allow-Origin", "*");
                headers.put("Cache-Control", "no-cache");
                return new WebResourceResponse(mimeType, "UTF-8", 200, "OK", headers, is);
            } catch (Exception e) {
                return null;
            }
        }

        @Override
        public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
            // 当处于断网/离线状态且主文档加载失败时，强制以本地 assets 闪存兜底渲染，杜绝白屏/恐龙页面
            if (failingUrl != null && !failingUrl.contains("/api/")) {
                view.loadUrl("file:///android_asset/web/index.html");
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
