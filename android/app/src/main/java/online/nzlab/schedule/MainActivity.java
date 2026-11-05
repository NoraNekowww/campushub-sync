package online.nzlab.schedule;

import android.annotation.SuppressLint;
import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.FileProvider;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import java.io.File;
import androidx.webkit.WebViewAssetLoader;

import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "CampusHub";
    private static final String APP_URL = "https://nzlab.online/schedule/";
    private static final String PREF_NAME = "campushub_auth";
    private static final String KEY_ADMIN_TOKEN = "admin_token";

    private WebView webView;
    private SwipeRefreshLayout swipeRefresh;
    private SharedPreferences prefs;
    private WebViewAssetLoader assetLoader;
    private ValueCallback<Uri[]> fileUploadCallback;

    private final ActivityResultLauncher<Intent> fileChooserLauncher =
            registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
                if (fileUploadCallback == null) {
                    return;
                }
                Uri[] results = null;
                if (result.getResultCode() == RESULT_OK && result.getData() != null) {
                    Intent data = result.getData();
                    if (data.getData() != null) {
                        results = new Uri[]{data.getData()};
                    } else if (data.getClipData() != null) {
                        int count = data.getClipData().getItemCount();
                        results = new Uri[count];
                        for (int i = 0; i < count; i++) {
                            results[i] = data.getClipData().getItemAt(i).getUri();
                        }
                    }
                }
                fileUploadCallback.onReceiveValue(results);
                fileUploadCallback = null;
            });

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
        // 采用标准缓存策略（静态资源由本地 WebViewAssetLoader 闪存 0 延迟秒开，API 动态请求走网络并遵循 HTTP 缓存协议）
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        // 彻底清空过往旧版本残留的 WebView HTTP 磁盘脏缓存，确保动态 API 实时穿透
        webView.clearCache(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        // 允许加载跨域网络图片和各种图床
        settings.setBlockNetworkImage(false);
        settings.setLoadsImagesAutomatically(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(true);
        settings.setAllowUniversalAccessFromFileURLs(true);
        settings.setSupportZoom(false);
        settings.setDisplayZoomControls(false);
        settings.setUserAgentString(settings.getUserAgentString() + " CampusHubAndroid/1.0");

        // 注入原生桥接接口，用于本地凭据双重兜底
        // 允许 WebView 远程调试（Chrome inspect）
        WebView.setWebContentsDebuggingEnabled(true);
        webView.addJavascriptInterface(new AuthBridge(), "NativeAuthBridge");

        // 1. 构建 Google 官方推荐的本地离线资源拦截器 WebViewAssetLoader
        // 直接拦截真实域名 https://nzlab.online/schedule/，同源环境 Cookie/Session 100% 自动互通！
        assetLoader = new WebViewAssetLoader.Builder()
                .setDomain("nzlab.online")
                .addPathHandler("/schedule/", new WebViewAssetLoader.PathHandler() {
                    @Override
                    public WebResourceResponse handle(String path) {
                        // 绝对不能拦截 API 请求，API 必须穿透给后端网络！
                        if (path != null && (path.startsWith("api/") || path.contains("/api/"))) {
                            return null;
                        }
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

        // 注入 WebChromeClient：优化渲染管道、控制台日志并支持点击 <input type="file"> 唤起原生文件管理器
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback, FileChooserParams fileChooserParams) {
                if (fileUploadCallback != null) {
                    fileUploadCallback.onReceiveValue(null);
                    fileUploadCallback = null;
                }
                fileUploadCallback = filePathCallback;

                Intent intent = null;
                if (fileChooserParams != null) {
                    try {
                        intent = fileChooserParams.createIntent();
                    } catch (Exception ignored) {
                    }
                }
                if (intent == null) {
                    intent = new Intent(Intent.ACTION_GET_CONTENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("*/*");
                }
                try {
                    fileChooserLauncher.launch(intent);
                    return true;
                } catch (Exception e) {
                    Log.e(TAG, "Failed to launch file chooser", e);
                    if (fileUploadCallback != null) {
                        fileUploadCallback.onReceiveValue(null);
                        fileUploadCallback = null;
                    }
                    return false;
                }
            }
        });

        // 进一步提速：允许后台线程优先渲染
        webView.getSettings().setRenderPriority(WebSettings.RenderPriority.HIGH);

        // 彻底取消上拉/下拉手势刷新，杜绝用户误触刷新拉取线上代码导致新老版本割裂
        swipeRefresh.setEnabled(false);
        swipeRefresh.setOnRefreshListener(() -> {
            swipeRefresh.setRefreshing(false);
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
            // 关键：非本应用域名的外部网络资源（如外部图床图片、CDN、Unsplash），绝对不拦截，放行让浏览器网络层直接加载！
            String host = request.getUrl().getHost();
            if (host != null && !host.equals("nzlab.online")) {
                return null;
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
            // 关键：非本应用域名的外部网络资源（如外部图床图片、CDN、Unsplash），绝对不拦截，放行让浏览器网络层直接加载！
            String host = uri.getHost();
            if (host != null && !host.equals("nzlab.online")) {
                return null;
            }
            return handleIntercept(uri);
        }

        private WebResourceResponse handleIntercept(Uri uri) {
            if (uri == null) return null;
            String path = uri.getPath();

            // 如果是 API 请求，绝对不拦截，放行给远程服务器网络！
            if (path != null && (path.contains("/api/") || path.startsWith("api/"))) {
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

        @JavascriptInterface
        public String getAppVersion() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            } catch (Exception e) {
                return "2.7.8";
            }
        }

        @JavascriptInterface
        public int getAppVersionCode() {
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    return (int) getPackageManager().getPackageInfo(getPackageName(), 0).getLongVersionCode();
                } else {
                    return getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                }
            } catch (Exception e) {
                return 1;
            }
        }

        /**
         * 原生应用内直接下载 APK 并通过系统 Intent 触发升级安装
         */
        @JavascriptInterface
        public void downloadAndInstallApk(String url) {
            if (url == null || url.trim().isEmpty()) return;
            runOnUiThread(() -> {
                try {
                    Toast.makeText(MainActivity.this, "开始在后台下载最新安装包...", Toast.LENGTH_SHORT).show();
                    DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                    if (dm == null) {
                        Intent browserIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        startActivity(browserIntent);
                        return;
                    }

                    Uri downloadUri = Uri.parse(url);
                    DownloadManager.Request request = new DownloadManager.Request(downloadUri);
                    request.setTitle("CampusHub 更新下载");
                    request.setDescription("正在下载最新版 CampusHub.apk...");
                    request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    request.setMimeType("application/vnd.android.package-archive");
                    request.setDestinationInExternalFilesDir(MainActivity.this, Environment.DIRECTORY_DOWNLOADS, "CampusHub.apk");

                    long downloadId = dm.enqueue(request);

                    BroadcastReceiver receiver = new BroadcastReceiver() {
                        @Override
                        public void onReceive(Context context, Intent intent) {
                            long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1);
                            if (id == downloadId) {
                                try {
                                    unregisterReceiver(this);
                                } catch (Exception ignored) {}

                                File apkFile = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "CampusHub.apk");
                                if (apkFile.exists()) {
                                    installApk(apkFile);
                                } else {
                                    Toast.makeText(MainActivity.this, "下载完成，请在通知栏或下载管理中打开安装", Toast.LENGTH_LONG).show();
                                }
                            }
                        }
                    };

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        registerReceiver(receiver, new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE), Context.RECEIVER_NOT_EXPORTED);
                    } else {
                        registerReceiver(receiver, new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE));
                    }
                } catch (Exception e) {
                    Log.e(TAG, "下载安装 APK 失败，降级为系统外部跳转", e);
                    try {
                        Intent browserIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        startActivity(browserIntent);
                    } catch (Exception ex) {
                        Toast.makeText(MainActivity.this, "下载失败，请手动访问发布页面", Toast.LENGTH_LONG).show();
                    }
                }
            });
        }
    }

    private void installApk(File apkFile) {
        try {
            Intent installIntent = new Intent(Intent.ACTION_VIEW);
            installIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            Uri apkUri;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                installIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                apkUri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", apkFile);
            } else {
                apkUri = Uri.fromFile(apkFile);
            }
            installIntent.setDataAndType(apkUri, "application/vnd.android.package-archive");
            startActivity(installIntent);
        } catch (Exception e) {
            Log.e(TAG, "调用系统安装器失败", e);
            Toast.makeText(this, "调起系统安装器失败，请前往下载目录点击安装", Toast.LENGTH_LONG).show();
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
