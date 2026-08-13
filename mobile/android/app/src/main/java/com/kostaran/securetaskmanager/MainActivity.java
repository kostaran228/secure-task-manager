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
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.text.TextUtils;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Locale;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private static final String CONNECTION_STORE = "task_manager_connection";
    private static final String SERVER_URL_KEY = "server_url";
    private boolean restoredConnection = false;
    private SpeechRecognizer voiceRecognizer;
    private boolean voiceStartPending = false;

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

    private void showConnectionSetup() {
        connectionStore().edit().remove(SERVER_URL_KEY).commit();
        restoredConnection = false;
        // This is Capacitor's bundled connection screen, available even when the remote tunnel is offline.
        getBridge().getWebView().loadUrl("http://localhost");
    }

    @Override
    public void onBackPressed() {
        String currentUrl = getBridge().getWebView().getUrl();
        String savedServer = connectionStore().getString(SERVER_URL_KEY, "");
        if (!savedServer.isBlank() && currentUrl != null && !currentUrl.startsWith("http://localhost")) {
            showConnectionSetup();
            return;
        }
        super.onBackPressed();
    }

    private void sendVoiceResult(String name, String value) {
        String script = "window." + name + " && window." + name + "(" + JSONObject.quote(value) + ");";
        getBridge().getWebView().evaluateJavascript(script, null);
    }

    private void startNativeVoice() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            voiceStartPending = true;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 102);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            sendVoiceResult("NativeTaskManagerVoiceError", "На этом телефоне недоступно распознавание речи.");
            return;
        }
        if (voiceRecognizer == null) {
            voiceRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
            voiceRecognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params) { sendVoiceResult("NativeTaskManagerVoiceState", "Слушаю…"); }
                @Override public void onBeginningOfSpeech() { }
                @Override public void onRmsChanged(float rmsdB) { }
                @Override public void onBufferReceived(byte[] buffer) { }
                @Override public void onEndOfSpeech() { }
                @Override public void onError(int error) { sendVoiceResult("NativeTaskManagerVoiceEnded", ""); }
                @Override public void onResults(Bundle results) {
                    ArrayList<String> items = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (items != null && !items.isEmpty() && !TextUtils.isEmpty(items.get(0))) sendVoiceResult("NativeTaskManagerVoiceResult", items.get(0));
                    sendVoiceResult("NativeTaskManagerVoiceEnded", "");
                }
                @Override public void onPartialResults(Bundle partialResults) { }
                @Override public void onEvent(int eventType, Bundle params) { }
            });
        }
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU");
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
        voiceRecognizer.startListening(intent);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 102) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED && voiceStartPending) startNativeVoice();
            else sendVoiceResult("NativeTaskManagerVoiceError", "Нужен доступ к микрофону для голосового помощника.");
            voiceStartPending = false;
        }
    }

    @Override
    public void onDestroy() {
        if (voiceRecognizer != null) voiceRecognizer.destroy();
        super.onDestroy();
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
            runOnUiThread(() -> showConnectionSetup());
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

        @JavascriptInterface
        public void startVoice() {
            runOnUiThread(() -> startNativeVoice());
        }

        @JavascriptInterface
        public void stopVoice() {
            runOnUiThread(() -> { if (voiceRecognizer != null) voiceRecognizer.cancel(); });
        }
    }
}
