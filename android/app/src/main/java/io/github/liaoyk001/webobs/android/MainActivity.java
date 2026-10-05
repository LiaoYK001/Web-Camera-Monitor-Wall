package io.github.liaoyk001.webobs.android;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Message;
import android.view.View;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.CheckBox;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Android owns navigation and permissions; product authentication stays on the backend. */
public final class MainActivity extends Activity {
    private static final int MICROPHONE = 101, FILE_PICKER = 102;
    private static final String REPOSITORY = "https://github.com/LiaoYK001/Web-Camera-Monitor-Wall";
    private SharedPreferences preferences;
    private FrameLayout root;
    private LinearLayout content;
    private WebView web;
    private ProgressBar progress;
    private TextView status;
    private String origin = "";
    private boolean foreground;
    private final List<WebView> projectors = new ArrayList<>();
    private final List<Dialog> projectorDialogs = new ArrayList<>();
    private PermissionRequest microphone;
    private ValueCallback<Uri[]> fileSelection;
    private View fullscreen;
    private AndroidUpdates updates;
    private AndroidUpdates.Listener updateDetails;
    private boolean installing;
    private int installEpoch;
    private WebChromeClient.CustomViewCallback fullscreenCallback;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        preferences = getSharedPreferences("connection", MODE_PRIVATE);
        updates = AndroidUpdates.get(this);
        setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);
        WebView.setWebContentsDebuggingEnabled((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        CookieManager.getInstance().setAcceptCookie(true);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(9, 11, 16));
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        root.addView(content, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets padding = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                view.setPadding(padding.left, padding.top, padding.right, padding.bottom); return insets;
            });
        } else root.setFitsSystemWindows(true);
        LinearLayout toolbar = new LinearLayout(this); toolbar.setPadding(dp(12), dp(4), dp(8), dp(4));
        toolbar.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView title = text("WebOBS", 20); title.setTextColor(Color.rgb(185, 255, 79));
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(48), 1));
        Button menu = button("菜单"); menu.setId(R.id.app_menu); menu.setContentDescription("客户端菜单");
        toolbar.addView(menu); menu.setOnClickListener(view -> menu(view)); content.addView(toolbar);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100); progress.setVisibility(View.GONE); content.addView(progress, new LinearLayout.LayoutParams(-1, dp(3)));
        status = text("先连接你的 WebOBS 服务器", 13); status.setPadding(dp(12), dp(6), dp(12), dp(6)); content.addView(status);
        web = createWebView(); content.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        updateScreenPolicy();
        try { origin = ServerAddress.normalize(preferences.getString("server", "")); } catch (IllegalArgumentException ignored) { }
        if (!origin.isEmpty()) web.loadUrl(origin);
        else showConnection();
    }

    private WebView createWebView() {
        WebView view = new WebView(this); view.setBackgroundColor(Color.rgb(9, 11, 16));
        WebSettings settings = view.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false); settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true); settings.setSupportMultipleWindows(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false); settings.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, false);
        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView current, WebResourceRequest request) {
                String url = request.getUrl().toString();
                if (ServerAddress.sameOrigin(url, origin)) return false;
                if (request.isForMainFrame() && request.hasGesture()) openExternal(url);
                return true;
            }
            @Override public void onPageStarted(WebView current, String url, android.graphics.Bitmap icon) {
                current.setTag(false);
                if (!url.equals("about:blank") && !ServerAddress.sameOrigin(url, origin)) { current.stopLoading(); return; }
                if (current == web) { status.setText("正在连接服务器…"); status.setVisibility(View.VISIBLE); }
            }
            @Override public void onPageFinished(WebView current, String url) {
                CookieManager.getInstance().flush();
                notifyVisibility(current);
                if (current == web && ServerAddress.sameOrigin(url, origin) && !Boolean.TRUE.equals(current.getTag())) status.setVisibility(View.GONE);
            }
            @Override public void onReceivedError(WebView current, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && current == web) { current.setTag(true); status.setText("服务暂不可用：请确认网络和服务器，或通过菜单重新连接。"); status.setVisibility(View.VISIBLE); }
            }
            @Override public void onReceivedSslError(WebView current, SslErrorHandler handler, SslError error) {
                handler.cancel();
                current.setTag(true);
                status.setText(R.string.certificate_error); status.setVisibility(View.VISIBLE);
            }
        });
        view.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView current, int value) { if (current == web) { progress.setProgress(value); progress.setVisibility(value == 100 ? View.GONE : View.VISIBLE); } }
            @Override public void onPermissionRequest(PermissionRequest request) { runOnUiThread(() -> requestMicrophone(request)); }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) { if (microphone == request) microphone = null; }
            @Override public boolean onShowFileChooser(WebView current, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (!ServerAddress.sameOrigin(current.getUrl(), origin)) return false;
                if (fileSelection != null) fileSelection.onReceiveValue(null);
                fileSelection = callback;
                Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                picker.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(picker, FILE_PICKER); return true; }
                catch (android.content.ActivityNotFoundException error) { fileSelection.onReceiveValue(null); fileSelection = null; return false; }
            }
            @Override public boolean onCreateWindow(WebView current, boolean dialog, boolean gesture, Message result) {
                if (!gesture || projectors.size() >= 4 || !ServerAddress.sameOrigin(current.getUrl(), origin)) return false;
                WebView child = createWebView(); Dialog window = new Dialog(MainActivity.this);
                LinearLayout frame = new LinearLayout(MainActivity.this); frame.setOrientation(LinearLayout.VERTICAL);
                Button close = button("关闭投影 / 子窗口"); frame.addView(close); frame.addView(child, new LinearLayout.LayoutParams(-1, 0, 1));
                window.setContentView(frame); window.setOnDismissListener(ignored -> { projectors.remove(child); projectorDialogs.remove(window); child.stopLoading(); child.destroy(); });
                close.setOnClickListener(ignored -> window.dismiss()); projectors.add(child); projectorDialogs.add(window);
                window.show(); window.getWindow().setLayout(-1, -1);
                ((WebView.WebViewTransport) result.obj).setWebView(child); result.sendToTarget(); return true;
            }
            @Override public void onShowCustomView(View view, CustomViewCallback callback) {
                if (fullscreen != null) { callback.onCustomViewHidden(); return; }
                fullscreen = view; fullscreenCallback = callback; content.setVisibility(View.GONE);
                root.addView(view, new FrameLayout.LayoutParams(-1, -1));
                getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
            }
            @Override public void onHideCustomView() { hideFullscreen(); }
        });
        // No addJavascriptInterface: pages receive no native filesystem or command bridge.
        return view;
    }

    private void showConnection() {
        LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(dp(20), dp(8), dp(20), dp(8));
        TextView guide = text("输入 Windows 客户端或 Docker / Podman 部署的 HTTPS 地址。使用同一服务器账号，Scenes、监听与播放偏好会自动同步。", 14); form.addView(guide);
        EditText address = new EditText(this); address.setId(R.id.server_address); address.setSingleLine(true); address.setHint("https://你的服务器:端口");
        address.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        address.setText(origin); form.addView(address, new LinearLayout.LayoutParams(-1, dp(60)));
        TextView explanation = text("证书：在系统安装服务器 CA 后连接，不接受无效证书。模拟器本机联调可通过 ADB reverse 使用 http://127.0.0.1:端口。", 12); form.addView(explanation);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("连接 WebOBS 服务器").setView(form).setPositiveButton("连接", null).setNegativeButton("稍后", null).create();
        dialog.setOnShowListener(ignored -> {
            Button connect = dialog.getButton(AlertDialog.BUTTON_POSITIVE); connect.setId(R.id.connect_server);
            connect.setOnClickListener(view -> {
                try {
                    String next = ServerAddress.normalize(address.getText().toString());
                    completeMicrophone(false);
                    if (fileSelection != null) { fileSelection.onReceiveValue(null); fileSelection = null; }
                    for (Dialog child : new ArrayList<>(projectorDialogs)) child.dismiss();
                    origin = next; preferences.edit().putString("server", origin).apply();
                    web.stopLoading(); web.clearHistory(); web.loadUrl(origin); dialog.dismiss();
                } catch (IllegalArgumentException error) { address.setError(error.getMessage()); }
            });
        }); dialog.show();
    }

    private void menu(View anchor) {
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) android.util.Log.d("WebOBSAndroid", "Opening native menu");
        // A scrollable system dialog avoids clipped edge-anchored popup menus on
        // Android 15 edge-to-edge and emulator landscape windows.
        boolean keepScreen = preferences.getBoolean("keepScreenOn", true);
        String[] items = {"连接 / 切换服务器", "刷新页面", "保持亮屏（" + (keepScreen ? "已开启" : "已关闭") + "）", "关于与检查更新", "退出客户端"};
        new AlertDialog.Builder(this).setTitle("客户端菜单").setItems(items, (dialog, index) -> {
            switch (index) {
                case 0: showConnection(); break;
                case 1: web.reload(); break;
                case 2: preferences.edit().putBoolean("keepScreenOn", !keepScreen).apply(); updateScreenPolicy(); break;
                case 3: showAbout(); break;
                case 4: finish(); break;
                default: break;
            }
        }).setNegativeButton("取消", null).show();
    }

    private void showAbout() {
        String version = "未报告";
        try { version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName; } catch (PackageManager.NameNotFoundException ignored) { }
        LinearLayout details = new LinearLayout(this); details.setOrientation(LinearLayout.VERTICAL); details.setPadding(dp(20), dp(8), dp(20), dp(8));
        String webview = WebView.getCurrentWebViewPackage() == null ? "未报告" : WebView.getCurrentWebViewPackage().versionName;
        details.addView(text("WebOBS Android · " + version + "\nWebView " + webview + "\nGPL-2.0-or-later\n\n连接现有后端，复用账号、场景及声音偏好。APK 使用本机自签密钥，不需商业证书；后续覆盖安装必须使用同一密钥。", 14));
        for (String[] option : new String[][]{{"autoCheck", "自动检查更新（前台每 6 小时）"}, {"autoDownload", "自动下载可验证更新（安装需确认）"}, {"wifiOnly", "仅 Wi-Fi 下载更新（下次下载生效）"}}) {
            CheckBox toggle = new CheckBox(this); toggle.setText(option[1]); toggle.setTextColor(Color.rgb(210, 220, 233));
            toggle.setChecked(updates.setting(option[0])); toggle.setOnCheckedChangeListener((view, checked) -> updates.setting(option[0], checked)); details.addView(toggle);
        }
        TextView updateStatus = text(updates.message, 14); updateStatus.setId(R.id.update_status); details.addView(updateStatus);
        Button check = button("检查 GitHub 更新"), download = button("下载更新"), install = button("安装更新"), cancel = button("取消 / 删除已下载更新"), notes = button("查看更新发布说明");
        check.setId(R.id.update_check); download.setId(R.id.update_download); install.setId(R.id.update_install); cancel.setId(R.id.update_cancel);
        Button source = button("GitHub 开源仓库"), releases = button("版本发布记录"), issues = button("反馈问题");
        for (Button button : Arrays.asList(check, download, install, cancel, notes, source, releases, issues)) details.addView(button);
        check.setOnClickListener(view -> updates.check(true)); download.setOnClickListener(view -> updates.download());
        install.setOnClickListener(view -> prepareInstall()); cancel.setOnClickListener(view -> updates.cancel());
        notes.setOnClickListener(view -> openExternal(updates.releaseUrl));
        AndroidUpdates.Listener listener = () -> {
            updateStatus.setText(updates.message);
            boolean busy = Arrays.asList("checking", "downloading", "verifying").contains(updates.phase);
            check.setEnabled(!busy && !updates.phase.equals("ready"));
            download.setVisibility(updates.asset != null && !busy && !updates.phase.equals("ready") ? View.VISIBLE : View.GONE);
            install.setVisibility(updates.phase.equals("ready") ? View.VISIBLE : View.GONE);
            cancel.setVisibility(Arrays.asList("downloading", "verifying", "ready").contains(updates.phase) ? View.VISIBLE : View.GONE);
        };
        source.setOnClickListener(view -> openExternal(REPOSITORY)); releases.setOnClickListener(view -> openExternal(REPOSITORY + "/releases")); issues.setOnClickListener(view -> openExternal(REPOSITORY + "/issues"));
        ScrollView scroll = new ScrollView(this); scroll.addView(details);
        AlertDialog about = new AlertDialog.Builder(this).setTitle("关于 WebOBS").setView(scroll).setPositiveButton("关闭", null).create();
        if (updateDetails != null) updates.unlisten(updateDetails);
        updateDetails = listener; updates.listen(listener);
        about.setOnDismissListener(dialog -> { updates.unlisten(listener); if (updateDetails == listener) updateDetails = null; }); about.show();
    }

    private void prepareInstall() {
        if (installing || !foreground) return;
        installing = true; int token = ++installEpoch;
        if (!getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(this).setTitle("允许 WebOBS 安装更新")
                    .setMessage("系统尚未允许此来源安装 APK。可打开系统设置授权，返回后再点击安装更新。不会自动安装，现有服务器与账号数据保留。")
                    .setPositiveButton("打开系统设置", (dialog, which) -> {
                        try { startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName()))); }
                        catch (android.content.ActivityNotFoundException error) { Toast.makeText(this, "系统安装设置不可用，请查看发布说明手动更新。", Toast.LENGTH_LONG).show(); }
                    }).setNegativeButton("稍后", null).setOnDismissListener(dialog -> endInstall()).show(); return;
        }
        checkInstallWork(new ArrayList<>(projectors), 0, false, token, () -> {
            new AlertDialog.Builder(this).setTitle("安装客户端更新？")
                    .setMessage("安装会关闭客户端，请确认所有草稿已保存。服务器的监控、录像与导出继续运行；使用相同签名覆盖安装保留连接、账号与偏好。系统还会要求你确认。")
                    .setPositiveButton("校验并交给系统安装", (dialog, which) -> updates.verifyForInstall(valid -> {
                        if (!valid || isFinishing() || isDestroyed() || !foreground || token != installEpoch) { endInstall(); return; }
                        checkInstallWork(new ArrayList<>(projectors), 0, false, token, () -> {
                            try {
                                Uri uri = Uri.parse("content://" + getPackageName() + ".updates/apk/" + updates.asset.sha256);
                                startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));
                            } catch (android.content.ActivityNotFoundException | SecurityException error) { Toast.makeText(this, "系统安装器不可用或权限已撤回；客户端可继续使用，请稍后重试。", Toast.LENGTH_LONG).show(); }
                            finally { endInstall(); }
                        });
                    })).setNegativeButton("稍后", (dialog, which) -> endInstall()).setOnCancelListener(dialog -> endInstall()).show();
        });
    }
    private void endInstall() { installing = false; installEpoch++; }
    private void checkInstallWork(List<WebView> children, int index, boolean unknown, int token, Runnable complete) {
        if (isFinishing() || isDestroyed() || !foreground || token != installEpoch) return;
        WebView target = index == 0 ? web : children.get(index - 1);
        if (!ServerAddress.sameOrigin(target.getUrl(), origin)) {
            continueInstallWork(children, index, true, token, complete); return;
        }
        // Fixed read-only query, with a deadline even if Chromium does not call back.
        android.os.Handler deadline = new android.os.Handler(android.os.Looper.getMainLooper()); boolean[] done = {false};
        Runnable timeout = () -> { if (!done[0]) { done[0] = true; continueInstallWork(children, index, true, token, complete); } };
        deadline.postDelayed(timeout, 3000);
        try { target.evaluateJavascript("(()=>{try{const s=window.webobsUpdateWork?.();return s&&typeof s.dirty==='boolean'&&typeof s.exporting==='boolean'?JSON.stringify({dirty:s.dirty,exporting:s.exporting}):null}catch{return null}})()", value -> {
            if (done[0] || isFinishing() || isDestroyed() || !foreground || token != installEpoch) return;
            done[0] = true; deadline.removeCallbacks(timeout);
            if (value == null || value.length() > 256) { continueInstallWork(children, index, true, token, complete); return; }
            try {
                Object decoded = new org.json.JSONTokener(value).nextValue();
                if (!(decoded instanceof String)) { continueInstallWork(children, index, true, token, complete); return; }
                org.json.JSONObject work = new org.json.JSONObject((String) decoded);
                if (!(work.opt("dirty") instanceof Boolean) || !(work.opt("exporting") instanceof Boolean)) { continueInstallWork(children, index, true, token, complete); return; }
                if (work.optBoolean("dirty") || work.optBoolean("exporting")) {
                    endInstall();
                    new AlertDialog.Builder(this).setTitle("请先处理当前工作")
                            .setMessage("主页面或投影仍有未保存草稿、保存或导出任务。请保存或处理完成后再次安装；已下载更新保留。")
                            .setPositiveButton("返回处理", null).show(); return;
                }
                continueInstallWork(children, index, unknown, token, complete);
            } catch (org.json.JSONException error) { continueInstallWork(children, index, true, token, complete); }
        }); } catch (RuntimeException error) {
            done[0] = true; deadline.removeCallbacks(timeout); continueInstallWork(children, index, true, token, complete);
        }
    }
    private void continueInstallWork(List<WebView> children, int index, boolean unknown, int token, Runnable complete) {
        if (isFinishing() || isDestroyed() || !foreground || token != installEpoch) return;
        if (index < children.size()) { checkInstallWork(children, index + 1, unknown, token, complete); return; }
        if (unknown) new AlertDialog.Builder(this).setTitle("确认页面工作已保存")
                .setMessage("当前后端页面未报告草稿或任务状态，可能尚未连接、版本较旧或响应超时。请自行确认已保存；服务端任务不会因客户端安装而停止。")
                .setPositiveButton("已保存，继续", (dialog, which) -> complete.run()).setNegativeButton("返回处理", (dialog, which) -> endInstall()).setOnCancelListener(dialog -> endInstall()).show();
        else complete.run();
    }

    private void requestMicrophone(PermissionRequest request) {
        if (!ServerAddress.sameOrigin(request.getOrigin().toString(), origin) || !Arrays.asList(request.getResources()).contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE) || microphone != null) { request.deny(); return; }
        microphone = request;
        new AlertDialog.Builder(this).setTitle("允许麦克风对讲？").setMessage("仅向当前 WebOBS 服务器开放麦克风；取消后仍可观看和监听视频。").setPositiveButton("允许", (dialog, which) -> {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) completeMicrophone(true);
            else requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MICROPHONE);
        }).setNegativeButton("取消", (dialog, which) -> completeMicrophone(false)).setOnCancelListener(dialog -> completeMicrophone(false)).show();
    }
    private void completeMicrophone(boolean allowed) {
        PermissionRequest request = microphone; microphone = null;
        if (request == null) return;
        if (allowed && ServerAddress.sameOrigin(request.getOrigin().toString(), origin)) request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}); else request.deny();
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) { super.onRequestPermissionsResult(code, permissions, results); if (code == MICROPHONE) completeMicrophone(results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED); }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != FILE_PICKER || fileSelection == null) return;
        ArrayList<Uri> selected = new ArrayList<>();
        if (result == RESULT_OK && data != null) {
            if (data.getClipData() != null) { for (int index = 0; index < Math.min(16, data.getClipData().getItemCount()); index++) { Uri uri = data.getClipData().getItemAt(index).getUri(); if ("content".equals(uri.getScheme())) selected.add(uri); } }
            else if (data.getData() != null && "content".equals(data.getData().getScheme())) selected.add(data.getData());
        }
        fileSelection.onReceiveValue(selected.isEmpty() ? null : selected.toArray(new Uri[0])); fileSelection = null;
    }

    private void openExternal(String url) {
        try {
            java.net.URI uri = new java.net.URI(url);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getRawUserInfo() != null) return;
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception error) { Toast.makeText(this, "无法打开链接，请安装或启用系统浏览器。", Toast.LENGTH_LONG).show(); }
    }
    private void hideFullscreen() {
        if (fullscreen == null) return;
        root.removeView(fullscreen); fullscreen = null; content.setVisibility(View.VISIBLE);
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        if (fullscreenCallback != null) fullscreenCallback.onCustomViewHidden(); fullscreenCallback = null;
    }
    private void updateScreenPolicy() { if (preferences.getBoolean("keepScreenOn", true)) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); }
    private void notifyVisibility(WebView view) {
        if (!ServerAddress.sameOrigin(view.getUrl(), origin)) return;
        // Only a fixed lifecycle signal is sent into the chosen product page.
        // Older WebViews do not reliably propagate Activity visibility to DOM.
        String script = "window.webobsAndroidForeground=" + foreground + ";window.dispatchEvent(new Event('webobs:visibility'));";
        if (!foreground) script += "document.querySelectorAll('video,audio').forEach(v=>v.pause());";
        view.evaluateJavascript(script, null);
    }
    @Override protected void onResume() { super.onResume(); foreground = true; if (updates != null) updates.foreground(true); if (web != null) { web.setVisibility(View.VISIBLE); web.onResume(); web.resumeTimers(); notifyVisibility(web); } for (WebView child : projectors) { child.setVisibility(View.VISIBLE); child.onResume(); notifyVisibility(child); } }
    @Override protected void onPause() { foreground = false; CookieManager.getInstance().flush(); if (web != null) { notifyVisibility(web); web.onPause(); } for (WebView child : projectors) { notifyVisibility(child); child.onPause(); } super.onPause(); }
    @Override protected void onStop() {
        endInstall();
        if (updates != null) updates.foreground(false);
        // onPause alone does not notify Chromium's Page Visibility API. Preserve
        // the DOM/drafts while allowing existing WebUI media lifecycle to suspend.
        if (web != null) { web.setVisibility(View.INVISIBLE); web.pauseTimers(); }
        for (WebView child : projectors) child.setVisibility(View.INVISIBLE);
        super.onStop();
    }
    @Override public void onBackPressed() { if (fullscreen != null) hideFullscreen(); else if (web != null && web.canGoBack()) web.goBack(); else new AlertDialog.Builder(this).setMessage("退出 WebOBS 客户端？服务器继续运行。").setPositiveButton("退出", (dialog, which) -> finish()).setNegativeButton("取消", null).show(); }
    @Override public boolean onKeyUp(int key, KeyEvent event) {
        if (key == KeyEvent.KEYCODE_MENU) { menu(web); return true; }
        return super.onKeyUp(key, event);
    }
    @Override protected void onDestroy() {
        if (updates != null && updateDetails != null) updates.unlisten(updateDetails);
        completeMicrophone(false);
        if (fileSelection != null) { fileSelection.onReceiveValue(null); fileSelection = null; }
        for (Dialog dialog : new ArrayList<>(projectorDialogs)) dialog.dismiss();
        if (web != null) { web.stopLoading(); web.destroy(); }
        super.onDestroy();
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size) { TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(Color.rgb(210, 220, 233)); return view; }
    private Button button(String value) { Button view = new Button(this); view.setText(value); view.setTextColor(Color.rgb(185, 255, 79)); view.setMinHeight(dp(48)); return view; }
}
