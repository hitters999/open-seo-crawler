package com.openseocrawler.app

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.inputmethod.InputMethodManager
import android.content.Context
import android.content.SharedPreferences
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var preferences: SharedPreferences

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        preferences = getSharedPreferences("open_seo_crawler", MODE_PRIVATE)

        val configuredUrl = preferences.getString("server_url", null)
            ?: BuildConfig.APP_URL.trim().takeIf { it.isNotEmpty() }

        if (configuredUrl == null) {
            showSetupScreen()
        } else {
            openCrawler(configuredUrl)
        }
    }

    private fun showSetupScreen() {
        val padding = (24 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(padding, padding, padding, padding)
        }

        val title = TextView(this).apply {
            text = "Open SEO Crawler"
            textSize = 26f
            setTextColor(0xFF111827.toInt())
        }
        val help = TextView(this).apply {
            text = "Enter the address of the computer or server running the Flask app.\n\nSame Wi-Fi example: http://192.168.1.20:5002/\nPublic server example: https://crawler.example.com/"
            textSize = 16f
            setTextColor(0xFF374151.toInt())
            setPadding(0, padding / 2, 0, padding / 2)
        }
        val input = EditText(this).apply {
            hint = "http://192.168.1.20:5002/"
            textSize = 16f
            singleLine = true
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI
        }
        val connect = Button(this).apply {
            text = "Connect"
            setOnClickListener {
                val url = input.text.toString().trim()
                if (!isValidServerUrl(url)) {
                    input.error = "Enter a valid http:// or https:// server URL"
                    return@setOnClickListener
                }
                preferences.edit().putString("server_url", normalizeUrl(url)).apply()
                (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
                    .hideSoftInputFromWindow(input.windowToken, 0)
                openCrawler(normalizeUrl(url))
            }
        }

        root.addView(title, LinearLayout.LayoutParams(-1, LinearLayout.LayoutParams.WRAP_CONTENT))
        root.addView(help, LinearLayout.LayoutParams(-1, LinearLayout.LayoutParams.WRAP_CONTENT))
        root.addView(input, LinearLayout.LayoutParams(-1, LinearLayout.LayoutParams.WRAP_CONTENT))
        root.addView(connect, LinearLayout.LayoutParams(-1, LinearLayout.LayoutParams.WRAP_CONTENT))
        setContentView(root)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun openCrawler(url: String) {
        refresh = SwipeRefreshLayout(this)
        webView = WebView(this)
        refresh.addView(webView)
        setContentView(refresh)

        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.allowFileAccess = false
        webView.settings.setSupportZoom(false)
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, pageUrl: String?, favicon: Bitmap?) {
                refresh.isRefreshing = true
            }

            override fun onPageFinished(view: WebView?, pageUrl: String?) {
                refresh.isRefreshing = false
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: android.webkit.WebResourceError?) {
                refresh.isRefreshing = false
                if (request?.isForMainFrame == true) {
                    Toast.makeText(this@MainActivity, "Cannot reach $url. Check server URL and Wi-Fi.", Toast.LENGTH_LONG).show()
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean = false
        }
        refresh.setOnRefreshListener { webView.reload() }
        webView.loadUrl(url)
    }

    private fun isValidServerUrl(value: String): Boolean {
        val parsed = runCatching { Uri.parse(value) }.getOrNull() ?: return false
        return (parsed.scheme == "http" || parsed.scheme == "https") && !parsed.host.isNullOrBlank()
    }

    private fun normalizeUrl(value: String): String = if (value.endsWith("/")) value else "$value/"

    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }
}
