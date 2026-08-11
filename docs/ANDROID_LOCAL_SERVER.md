# Android APK and local server

The debug APK is a native Android WebView wrapper for the Task Manager dashboard. It opens `http://192.168.0.100:8000`, which is the current Wi-Fi address of this computer.

Keep the Docker application running and connect the phone to the same Wi-Fi network. If the computer receives a new local IP address, update `mobile/capacitor.config.json`, run `npm run android:sync`, and rebuild the APK.

The APK is intended for local-network use. Before using it, allow inbound TCP port 8000 through Windows Firewall for private networks.
