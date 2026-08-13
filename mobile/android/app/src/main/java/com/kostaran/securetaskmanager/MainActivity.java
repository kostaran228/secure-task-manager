package com.kostaran.securetaskmanager;

import android.os.Bundle;
import android.content.SharedPreferences;
import android.webkit.JavascriptInterface;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new ServerNavigator(), "NativeTaskManager");
        String savedServer = getPreferences(MODE_PRIVATE).getString("server_url", null);
        if (savedServer != null && !savedServer.isBlank()) {
            getBridge().getWebView().postDelayed(() -> getBridge().getWebView().loadUrl(savedServer), 250);
        }
    }

    private class ServerNavigator {
        @JavascriptInterface
        public void openServer(String url) {
            getPreferences(MODE_PRIVATE).edit().putString("server_url", url).apply();
            runOnUiThread(() -> getBridge().getWebView().loadUrl(url));
        }

        @JavascriptInterface
        public void forgetServer() {
            getPreferences(MODE_PRIVATE).edit().remove("server_url").apply();
        }
    }
}
