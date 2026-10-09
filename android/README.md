# Android APK wrapper

The Android app is a small WebView wrapper around the Flask UI. It loads the crawler URL passed with the Gradle property `appUrl`.

## GitHub Actions

The workflow at `.github/workflows/build-apk.yml` builds a debug APK on every push to `master` and on manual runs. The APK is available in the workflow run's **Artifacts** section.

For a real device, set a repository variable named `APP_URL` to the public URL where the Flask app is hosted. A manual workflow run can override it with the `app_url` input.

The default `http://10.0.2.2:5002/` URL is useful only when running the Flask server on the Android emulator host. A physical phone cannot reach the developer machine through that address.

> This wrapper does not package the Python/Flask server into the APK. The web app must be reachable at `APP_URL`.
