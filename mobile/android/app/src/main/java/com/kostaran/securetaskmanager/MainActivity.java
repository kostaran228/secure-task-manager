package com.kostaran.securetaskmanager;

import android.os.Bundle;
import android.webkit.JavascriptInterface;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new ServerNavigator(), "NativeTaskManager");
    }

    private class ServerNavigator {
        @JavascriptInterface
        public void openServer(String url) {
            runOnUiThread(() -> getBridge().getWebView().loadUrl(url));
        }
    }
}
