package com.kostaran.securetaskmanager;

import android.Manifest;
import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Build;
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

    private PendingIntent reminderIntent(String taskId, String title, int intervalMinutes) {
        Intent intent = new Intent(MainActivity.this, ReminderReceiver.class);
        intent.putExtra("task_id", taskId);
        intent.putExtra("title", title);
        intent.putExtra("interval_minutes", intervalMinutes);
        return PendingIntent.getBroadcast(MainActivity.this, taskId.hashCode(), intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
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

        @JavascriptInterface
        public void scheduleReminder(String taskId, String title, int intervalMinutes) {
            int minutes = Math.max(15, intervalMinutes);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 101));
            }
            AlarmManager alarms = (AlarmManager) getSystemService(Context.ALARM_SERVICE);
            PendingIntent pending = reminderIntent(taskId, title, minutes);
            alarms.cancel(pending);
            long interval = minutes * 60_000L;
            alarms.setInexactRepeating(AlarmManager.RTC_WAKEUP, System.currentTimeMillis() + interval, interval, pending);
        }

        @JavascriptInterface
        public void cancelReminder(String taskId) {
            AlarmManager alarms = (AlarmManager) getSystemService(Context.ALARM_SERVICE);
            PendingIntent pending = reminderIntent(taskId, "", 15);
            alarms.cancel(pending);
            pending.cancel();
        }
    }
}
