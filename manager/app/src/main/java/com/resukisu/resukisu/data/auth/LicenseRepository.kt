package com.resukisu.resukisu.data.auth

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.resukisu.resukisu.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URI
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.util.UUID
import javax.net.ssl.HttpsURLConnection

class LicenseFailure(val reason: String) : Exception(reason)

class LicenseRepository(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences("license_session", Context.MODE_PRIVATE)
    private val alias = "shivxroot_license_device_v1"
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    init {
        if (!store.containsAlias(alias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                    .setKeySize(2048)
                    .setDigests(KeyProperties.DIGEST_SHA256)
                    .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                    .build())
            }.generateKeyPair()
        }
    }

    val configured: Boolean get() = BuildConfig.LICENSE_SERVER_URL.startsWith("https://")
    val hasSession: Boolean get() = preferences.contains("token")

    private fun sign(message: String): String = Base64.encodeToString(
        Signature.getInstance("SHA256withRSA").run {
            initSign(store.getKey(alias, null) as java.security.PrivateKey)
            update(message.toByteArray(Charsets.UTF_8))
            sign()
        }, Base64.NO_WRAP)

    private suspend fun post(path: String, body: JSONObject): JSONObject = withContext(Dispatchers.IO) {
        if (!configured) throw LicenseFailure("not_configured")
        val url = URI(BuildConfig.LICENSE_SERVER_URL.trimEnd('/') + path).toURL()
        val connection = url.openConnection() as HttpsURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 10_000
            connection.readTimeout = 12_000
            connection.instanceFollowRedirects = false
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("User-Agent", "shivxroot-manager/${BuildConfig.VERSION_NAME} (Android ${Build.VERSION.RELEASE})")
            connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader()?.use { it.readText() } ?: "{}"
            val data = JSONObject(response)
            if (status !in 200..299) throw LicenseFailure(data.optString("error", "unavailable"))
            data
        } finally {
            connection.disconnect()
        }
    }

    suspend fun requestCode(license: String): String {
        val publicKey = Base64.encodeToString(store.getCertificate(alias).publicKey.encoded, Base64.NO_WRAP)
        return post("/v1/request", JSONObject()
            .put("license", license.trim())
            .put("public_key", publicKey)
            .put("device", "${Build.MANUFACTURER} ${Build.MODEL} / Android ${Build.VERSION.RELEASE}"))
            .getString("challenge")
    }

    suspend fun verify(challenge: String, code: String) {
        val response = post("/v1/verify", JSONObject()
            .put("challenge", challenge).put("code", code)
            .put("signature", sign("$challenge:$code")))
        preferences.edit().putString("token", response.getString("token")).apply()
    }

    suspend fun validate(): Boolean {
        val token = preferences.getString("token", null) ?: return false
        val timestamp = (System.currentTimeMillis() / 1000).toString()
        val nonce = UUID.randomUUID().toString()
        try {
            return post("/v1/session", JSONObject().put("token", token)
                .put("timestamp", timestamp).put("nonce", nonce)
                .put("signature", sign("$token:$timestamp:$nonce"))).getBoolean("valid")
        } catch (e: LicenseFailure) {
            if (e.reason == "session_expired" || e.reason == "invalid_proof") {
                preferences.edit().remove("token").apply()
            }
            throw e
        }
    }
}
