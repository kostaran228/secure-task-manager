package com.kostaran.securetaskmanager;

import android.os.Bundle;
import android.content.SharedPreferences;
import android.webkit.JavascriptInterface;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private static final String CONNECTION_STORE = "task_manager_connection";
    private static final String SERVER_URL_KEY = "server_url";
    private boolean restoredConnection = false;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new ServerNavigator(), "NativeTaskManager");
        restoreLastServer();
    }

    private SharedPreferences connectionStore() {
        return getSharedPreferences(CONNECTION_STORE, MODE_PRIVATE);
    }

    private void restoreLastServer() {
        if (restoredConnection) return;
        String savedServer = connectionStore().getString(SERVER_URL_KEY, "");
        if (savedServer.isBlank()) return;
        restoredConnection = true;
        // Wait until Capacitor finishes loading its bundled start screen, then replace it.
        getBridge().getWebView().postDelayed(() -> getBridge().getWebView().loadUrl(savedServer), 900);
    }

    private class ServerNavigator {
        @JavascriptInterface
        public void openServer(String url) {
            // commit() makes the connection durable before WebView leaves this screen.
            connectionStore().edit().putString(SERVER_URL_KEY, url).commit();
            runOnUiThread(() -> getBridge().getWebView().loadUrl(url));
        }

        @JavascriptInterface
        public void forgetServer() {
            connectionStore().edit().remove(SERVER_URL_KEY).commit();
            restoredConnection = false;
        }
    }
}
