package com.kirdev.pulsepc

import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.Executors

class ApiException(message: String, val code: Int = 0) : Exception(message)

/** Minimal client for the Pulse PC LAN API (modules/local_api.py on the PC). */
class PcApi(val host: String, val port: Int, private val token: String) {
    private fun open(path: String, method: String, body: JSONObject?, timeoutMs: Int): HttpURLConnection {
        val conn = URL("http://$host:$port$path").openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = timeoutMs
        conn.readTimeout = timeoutMs
        conn.setRequestProperty("Authorization", "Bearer $token")
        if (body != null) {
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
        }
        return conn
    }

    private fun request(path: String, method: String, body: JSONObject?, timeoutMs: Int = 8000): ByteArray {
        val conn = open(path, method, body, timeoutMs)
        try {
            val code = conn.responseCode
            if (code in 200..299) return conn.inputStream.use { it.readBytes() }
            val text = conn.errorStream?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
            val message = try { JSONObject(text).optString("error") } catch (_: Exception) { "" }
            throw ApiException(message.ifEmpty { "HTTP $code" }, code)
        } finally {
            conn.disconnect()
        }
    }

    fun getJson(path: String, timeoutMs: Int = 8000): JSONObject =
        JSONObject(String(request(path, "GET", null, timeoutMs), Charsets.UTF_8))
    fun postJson(path: String, body: JSONObject? = null): JSONObject {
        val bytes = request(path, "POST", body ?: JSONObject())
        return if (bytes.isEmpty()) JSONObject() else JSONObject(String(bytes, Charsets.UTF_8))
    }
    fun getBytes(path: String): ByteArray = request(path, "GET", null, 20000)

    /** Streams a PC file into [out]; returns the byte count. */
    fun download(pcPath: String, out: OutputStream): Long {
        val conn = open("/api/files/download?path=" + URLEncoder.encode(pcPath, "UTF-8"), "GET", null, 30000)
        try {
            if (conn.responseCode !in 200..299) throw ApiException(errorText(conn), conn.responseCode)
            return conn.inputStream.use { it.copyTo(out) }
        } finally {
            conn.disconnect()
        }
    }

    fun upload(name: String, input: InputStream): String {
        val conn = open("/api/files/upload?name=" + URLEncoder.encode(name, "UTF-8"), "POST", null, 60000)
        try {
            conn.doOutput = true
            conn.setChunkedStreamingMode(1 shl 16)
            conn.outputStream.use { input.copyTo(it) }
            if (conn.responseCode !in 200..299) throw ApiException(errorText(conn), conn.responseCode)
            return JSONObject(conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }).optString("message")
        } finally {
            conn.disconnect()
        }
    }

    private fun errorText(conn: HttpURLConnection): String {
        val text = conn.errorStream?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
        val message = try { JSONObject(text).optString("error") } catch (_: Exception) { "" }
        return message.ifEmpty { "HTTP ${conn.responseCode}" }
    }

    companion object {
        /** Broadcasts "PULSEPC?" and collects answers for [waitMs]: (name, host, port). */
        fun discover(prefix: String, waitMs: Int = 1500): List<Triple<String, String, Int>> {
            val found = LinkedHashMap<String, Triple<String, String, Int>>()
            try {
                java.net.DatagramSocket().use { socket ->
                    socket.broadcast = true
                    socket.soTimeout = 300
                    val ask = "PULSEPC?".toByteArray()
                    for (target in listOf("255.255.255.255", "$prefix.255")) {
                        try {
                            socket.send(java.net.DatagramPacket(ask, ask.size, java.net.InetAddress.getByName(target), 8766))
                        } catch (_: Exception) {}
                    }
                    val deadline = System.currentTimeMillis() + waitMs
                    val buffer = ByteArray(512)
                    while (System.currentTimeMillis() < deadline) {
                        try {
                            val packet = java.net.DatagramPacket(buffer, buffer.size)
                            socket.receive(packet)
                            val json = JSONObject(String(packet.data, 0, packet.length))
                            if (json.optString("app") == "PulsePC") {
                                val host = packet.address.hostAddress ?: continue
                                found[host] = Triple(json.optString("name", host), host, json.optInt("port", 8765))
                            }
                        } catch (_: java.net.SocketTimeoutException) {
                        } catch (_: Exception) {}
                    }
                }
            } catch (_: Exception) {}
            return found.values.toList()
        }

        /** Asks the PC owner (dialog on the PC) to allow this phone; returns the token. */
        fun pair(host: String, port: Int, device: String): JSONObject {
            val conn = URL("http://$host:$port/api/pair").openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 5000
            conn.readTimeout = 70000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            try {
                conn.outputStream.use { it.write(JSONObject().put("device", device).toString().toByteArray()) }
                val code = conn.responseCode
                if (code in 200..299) return JSONObject(conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) })
                val text = conn.errorStream?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
                val message = try { JSONObject(text).optString("error") } catch (_: Exception) { "" }
                throw ApiException(message.ifEmpty { "HTTP $code" }, code)
            } finally {
                conn.disconnect()
            }
        }

        /** /api/ping needs no token; returns the PC name or null. */
        fun ping(host: String, port: Int, timeoutMs: Int): String? = try {
            val conn = URL("http://$host:$port/api/ping").openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            try {
                val json = JSONObject(conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) })
                if (json.optString("app") == "PulsePC") json.optString("name") else null
            } finally {
                conn.disconnect()
            }
        } catch (_: Exception) {
            null
        }
    }
}

object Bg {
    private val pool = Executors.newFixedThreadPool(4)
    private val main = Handler(Looper.getMainLooper())

    fun <T> run(work: () -> T, onError: (Exception) -> Unit, onDone: (T) -> Unit) {
        pool.execute {
            try {
                val result = work()
                main.post { onDone(result) }
            } catch (e: Exception) {
                main.post { onError(e) }
            }
        }
    }

    fun submit(task: Runnable) = pool.execute(task)
    fun post(task: Runnable) = main.post(task)
    fun postDelayed(task: Runnable, ms: Long) = main.postDelayed(task, ms)
    fun removeCallbacks(task: Runnable) = main.removeCallbacks(task)
}
