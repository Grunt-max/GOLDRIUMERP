package kr.co.goldrium.king;

import android.content.Intent;
import android.app.DownloadManager;
import android.os.Environment;
import android.webkit.URLUtil;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.provider.MediaStore;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import java.io.File;

public class MainActivity extends ComponentActivity {
    private static final String ERP_URL = "https://desktop-1i805ut.tail587e4a.ts.net/";
    private static final int FILE_REQUEST = 42;
    private WebView webView;
    private ValueCallback<Uri[]> fileCallback;
    private Uri cameraUri;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        webView = new WebView(this);
        setContentView(webView);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) { @Override public void handleOnBackPressed() { handleBack(); } });
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        webView.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("desktop-1i805ut.tail587e4a.ts.net".equals(uri.getHost())) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
                return true;
            }
            @Override public void onReceivedError(WebView view, android.webkit.WebResourceRequest request, android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) Toast.makeText(MainActivity.this, "Tailscale 연결과 ERP 서버 상태를 확인하세요.", Toast.LENGTH_LONG).show();
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    if (params.isCaptureEnabled()) {
                        File directory = new File(getCacheDir(), "camera"); directory.mkdirs();
                        File image = File.createTempFile("goldrium-", ".jpg", directory);
                        cameraUri = FileProvider.getUriForFile(MainActivity.this, "kr.co.goldrium.king.files", image);
                        Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT, cameraUri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                        startActivityForResult(camera, FILE_REQUEST);
                    } else startActivityForResult(params.createIntent(), FILE_REQUEST);
                }
                catch (Exception e) { fileCallback = null; Toast.makeText(MainActivity.this, "사진 앱을 열 수 없습니다.", Toast.LENGTH_SHORT).show(); }
                return true;
            }
        });
        webView.setDownloadListener((url, userAgent, disposition, mimeType, size) -> {
            Uri uri = Uri.parse(url);
            if (!"https".equals(uri.getScheme()) || !Uri.parse(ERP_URL).getHost().equals(uri.getHost())) return;
            try {
                String filename = URLUtil.guessFileName(url, disposition, mimeType).replaceAll("[^a-zA-Z0-9._-]", "_");
                DownloadManager.Request download = new DownloadManager.Request(uri);
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) download.addRequestHeader("Cookie", cookie);
                download.addRequestHeader("User-Agent", userAgent);
                download.setMimeType(mimeType);
                download.setTitle(filename);
                download.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                if (android.os.Build.VERSION.SDK_INT >= 29) {
                    download.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
                } else {
                    download.setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, filename);
                }
                ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(download);
                Toast.makeText(this, "다운로드를 시작했습니다. 완료 알림에서 파일을 여세요.", Toast.LENGTH_LONG).show();
            } catch (Exception error) {
                Toast.makeText(this, "다운로드를 시작할 수 없습니다. 연결과 저장 공간을 확인하세요.", Toast.LENGTH_LONG).show();
            }
        });
        if (state == null) webView.loadUrl(destinationUrl(getIntent())); else webView.restoreState(state);
    }

    private String destinationUrl(Intent intent) {
        String destination = intent.getStringExtra("activity_destination");
        if ("entry".equals(destination)) return ERP_URL + "activities/#activity-entry";
        if ("list".equals(destination)) return ERP_URL + "activities/";
        return ERP_URL;
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        webView.loadUrl(destinationUrl(intent));
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_REQUEST && fileCallback != null) {
            Uri[] result = resultCode == RESULT_OK && cameraUri != null ? new Uri[]{cameraUri} : WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            fileCallback.onReceiveValue(result);
            fileCallback = null;
            cameraUri = null;
        }
    }
    private void handleBack() { if (webView.canGoBack()) webView.goBack(); else if (!ERP_URL.equals(webView.getUrl())) webView.loadUrl(ERP_URL); else webView.reload(); }
    @Override protected void onSaveInstanceState(Bundle out) { webView.saveState(out); super.onSaveInstanceState(out); }
}
