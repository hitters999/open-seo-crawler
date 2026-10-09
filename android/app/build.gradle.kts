plugins {
    id("com.android.application")
    kotlin("android")
}

val appUrl = (project.findProperty("appUrl") as String?)
    ?.trim()
    ?.takeIf { it.isNotEmpty() }
    ?: "http://10.0.2.2:5002/"

android {
    namespace = "com.openseocrawler.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.openseocrawler.app"
        minSdk = 23
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "APP_URL", "\"${appUrl.replace("\\", "\\\\").replace("\"", "\\\"")}\"")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    implementation("com.google.android.material:material:1.12.0")
}
