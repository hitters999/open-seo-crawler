# Android APK wrapper

The Android app is a small WebView wrapper around the Flask UI. It loads the crawler URL passed with the Gradle property `appUrl`.

## GitHub Actions

The workflow at `.github/workflows/build-apk.yml` builds a debug APK on every push to `master` and on manual runs. The APK is available in the workflow run's **Artifacts** section.

For a real device, set a repository variable named `APP_URL` to the public URL where the Flask app is hosted. A manual workflow run can override it with the `app_url` input. If no URL is supplied, the APK now opens a setup screen where the user can enter the server URL and it saves that value for the next launch.

Do not use `http://10.0.2.2:5002/` on a physical phone: `10.0.2.2` is an Android-emulator-only alias. For a phone on the same Wi-Fi, run the Flask app on the computer and enter the computer's LAN address, for example `http://192.168.1.20:5002/`. The Flask app already binds to `0.0.0.0:5002`; allow port 5002 through the computer firewall if needed. For access from outside the Wi-Fi, use an HTTPS public deployment URL instead.

> This wrapper does not package the Python/Flask server into the APK. The web app must be reachable at `APP_URL`.
