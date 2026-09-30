package com.kirdev.pulsepc

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.Icon
import android.media.MediaMetadata
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import org.json.JSONArray
import org.json.JSONObject

/**
 * Держит связь с подключённым ПК, пока приложение закрыто:
 *  - медиа‑уведомление (шторка и экран блокировки): обложка, трек, кнопки ⏮ ⏯ ⏭;
 *  - обычные уведомления, которые приходят с ПК (оповещения Pulse PC).
 */
class PulseService : Service() {
    private lateinit var thread: HandlerThread
    private lateinit var handler: Handler
    private lateinit var session: MediaSession
    private lateinit var notifications: NotificationManager
    private var api: PcApi? = null
    private var running = false
    private var tick = 0
    private var lastEventId = -1
    private var coverKey = ""
    private var cover: Bitmap? = null
    private var title = ""
    private var artist = ""
    private var status = "none"
    private var offline = false
    private var connected = false
    private val logo: Bitmap by lazy { BitmapFactory.decodeResource(resources, R.drawable.logo_emblem) }
    private var announced = false
    private var failCount = 0
    private var offlineNotified = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        notifications = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notifications.createNotificationChannel(
            NotificationChannel(CH_PLAYER, "Плеер ПК", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false); lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            })
        notifications.createNotificationChannel(
            NotificationChannel(CH_EVENTS, "Уведомления с ПК", NotificationManager.IMPORTANCE_DEFAULT))

        session = MediaSession(this, "PulsePC").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onPlay() = command("play")
                override fun onPause() = command("pause")
                override fun onSkipToNext() = command("next")
                override fun onSkipToPrevious() = command("prev")
                override fun onSeekTo(pos: Long) = command("seek", pos / 1000.0)
            })
            isActive = true
        }
        thread = HandlerThread("pulse-service").also { it.start() }
        handler = Handler(thread.looper)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
            ACTION_TOGGLE -> command("toggle")
            ACTION_NEXT -> command("next")
            ACTION_PREV -> command("prev")
            ACTION_VOL_UP -> volume("volup")
            ACTION_VOL_DOWN -> volume("voldown")
        }
        if (!running) {
            val pc = loadLastPc()
            if (pc == null) { stopSelf(); return START_NOT_STICKY }
            api = PcApi(pc.host, pc.port, pc.token)
            running = true
            startForegroundCompat()
            handler.post(::poll)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        handler.removeCallbacksAndMessages(null)
        thread.quitSafely()
        session.release()
        notifications.cancel(ID_PLAYER)
        super.onDestroy()
    }

    // ---------- Опрос ПК ----------

    private fun poll() {
        if (!running) return
        val client = api ?: return
        try {
            val player = client.getJson("/api/player/state").optJSONObject("player") ?: JSONObject()
            offline = false
            failCount = 0
            offlineNotified = false
            if (!connected) {
                connected = true
                announceConnection(firstTime = !announced)
                announced = true
            }
            status = player.optString("status", "none")
            title = player.optString("title")
            artist = player.optString("artist")
            val key = player.optString("cover")
            if (key != coverKey) {
                coverKey = key
                cover = if (key.isEmpty()) null else try {
                    val bytes = client.getBytes("/api/player/cover?key=" + java.net.URLEncoder.encode(key, "UTF-8"))
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                } catch (_: Exception) { null }
            }
            updateSession(player)
            if (tick++ % 2 == 0) pollEvents(client)
        } catch (_: Exception) {
            if (++failCount >= 2 || !announced) {
                offline = true
                connected = false
                status = "none"
                if (!offlineNotified && announced) {
                    offlineNotified = true
                    announceOffline()
                }
            }
        }
        notifications.notify(ID_PLAYER, buildPlayerNotification())
        handler.postDelayed(::poll, 2000)
    }

    private fun announceOffline() {
        val pc = loadLastPc()?.name ?: "ПК"
        val n = Notification.Builder(this, CH_EVENTS)
            .setSmallIcon(R.drawable.ic_stat_pulse).setColor(0xFF2A8CFF.toInt()).setLargeIcon(logo)
            .setContentTitle("ПК недоступен")
            .setContentText("Связь с $pc потеряна")
            .setContentIntent(openAppIntent())
            .setAutoCancel(true)
            .build()
        notifications.notify(ID_CONNECTED, n)
    }

    /** Уведомление «Подключено к ПК» при первом соединении и при восстановлении связи. */
    private fun announceConnection(firstTime: Boolean) {
        val pc = loadLastPc()?.name ?: "ПК"
        val n = Notification.Builder(this, CH_EVENTS)
            .setSmallIcon(R.drawable.ic_stat_pulse).setColor(0xFF2A8CFF.toInt()).setLargeIcon(logo)
            .setContentTitle(if (firstTime) "Подключено" else "Связь восстановлена")
            .setContentText(if (firstTime) "Вы управляете ПК $pc" else "Снова на связи с ПК $pc")
            .setContentIntent(openAppIntent())
            .setAutoCancel(true)
            .setTimeoutAfter(8000)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .build()
        notifications.notify(ID_CONNECTED, n)
    }

    private fun pollEvents(client: PcApi) {
        val json = client.getJson("/api/events?after=$lastEventId")
        val first = lastEventId < 0
        lastEventId = json.optInt("last", lastEventId)
        if (first) return // первый запрос только запоминает, что уже было
        val items: JSONArray = json.optJSONArray("events") ?: return
        for (i in 0 until items.length()) {
            val e = items.getJSONObject(i)
            val n = Notification.Builder(this, CH_EVENTS)
                .setSmallIcon(R.drawable.ic_stat_pulse).setColor(0xFF2A8CFF.toInt()).setLargeIcon(logo)
                .setContentTitle(e.optString("title", "Pulse PC"))
                .setContentText(e.optString("text"))
                .setStyle(Notification.BigTextStyle().bigText(e.optString("text")))
                .setContentIntent(openAppIntent())
                .setAutoCancel(true)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .build()
            notifications.notify(ID_EVENT_BASE + e.optInt("id") % 1000, n)
        }
    }

    // ---------- Команды ----------

    /** Громкость ПК: нажатия клавиш громкости (одно ≈ 2%), 5 нажатий за раз. */
    private fun volume(name: String) {
        val client = api ?: return
        handler.post {
            try { client.postJson("/api/media/$name", JSONObject().put("count", 1)) } catch (_: Exception) {}
        }
    }

    private fun command(name: String, value: Double? = null) {
        val client = api ?: return
        handler.post {
            try {
                client.postJson("/api/player/$name", if (value != null) JSONObject().put("value", value) else null)
            } catch (_: Exception) {}
            handler.removeCallbacks(::poll)
            handler.postDelayed(::poll, 400)
        }
    }

    // ---------- Уведомление и медиасессия ----------

    private fun updateSession(player: JSONObject) {
        val playing = status == "playing"
        val meta = MediaMetadata.Builder()
            .putString(MediaMetadata.METADATA_KEY_TITLE, title.ifEmpty { "Ничего не играет" })
            .putString(MediaMetadata.METADATA_KEY_ARTIST, artist)
            .putLong(MediaMetadata.METADATA_KEY_DURATION, (player.optDouble("duration", 0.0) * 1000).toLong())
        cover?.let { meta.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, it) }
        session.setMetadata(meta.build())
        val actions = PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or
            PlaybackState.ACTION_SKIP_TO_NEXT or PlaybackState.ACTION_SKIP_TO_PREVIOUS or PlaybackState.ACTION_SEEK_TO
        session.setPlaybackState(PlaybackState.Builder()
            .setActions(actions)
            .setState(
                when (status) { "playing" -> PlaybackState.STATE_PLAYING; "paused" -> PlaybackState.STATE_PAUSED; else -> PlaybackState.STATE_STOPPED },
                (player.optDouble("position", 0.0) * 1000).toLong(), if (playing) 1f else 0f)
            .build())
    }

    private fun action(icon: Int, label: String, act: String): Notification.Action {
        val pi = PendingIntent.getService(this, act.hashCode(), Intent(this, PulseService::class.java).setAction(act),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Action.Builder(Icon.createWithResource(this, icon), label, pi).build()
    }

    private fun openAppIntent() = PendingIntent.getActivity(this, 0,
        Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    private fun buildPlayerNotification(): Notification {
        val pc = loadLastPc()?.name ?: "ПК"
        val text = when {
            offline -> "ПК недоступен"
            status == "none" -> "Ничего не играет"
            else -> artist
        }
        val builder = Notification.Builder(this, CH_PLAYER)
            .setSmallIcon(R.drawable.ic_stat_pulse).setColor(0xFF2A8CFF.toInt()).setLargeIcon(logo)
            .setContentTitle(if (offline || status == "none") "Pulse PC · $pc" else title)
            .setContentText(text)
            .setSubText(pc)
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setCategory(Notification.CATEGORY_TRANSPORT)
        builder.setLargeIcon(cover ?: logo)
        if (status != "none") {
            builder.addAction(action(R.drawable.ic_prev, "Назад", ACTION_PREV))
            builder.addAction(action(if (status == "playing") R.drawable.ic_pause else R.drawable.ic_play,
                if (status == "playing") "Пауза" else "Играть", ACTION_TOGGLE))
            builder.addAction(action(R.drawable.ic_next, "Вперёд", ACTION_NEXT))
            builder.addAction(action(R.drawable.ic_voldown, "Тише", ACTION_VOL_DOWN))
            builder.addAction(action(R.drawable.ic_volup, "Громче", ACTION_VOL_UP))
            builder.setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0, 1, 2))
        } else {
            builder.setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken))
        }
        return builder.build()
    }

    private fun startForegroundCompat() {
        val n = buildPlayerNotification()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(ID_PLAYER, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        } else {
            startForeground(ID_PLAYER, n)
        }
    }

    private fun loadLastPc(): SavedPc? {
        val prefs = getSharedPreferences("pulse", Context.MODE_PRIVATE)
        val last = prefs.getString("last", null) ?: return null
        return try {
            val arr = JSONArray(prefs.getString("pcs", "[]"))
            (0 until arr.length()).map { arr.getJSONObject(it) }.firstOrNull { it.getString("name") == last }?.let {
                SavedPc(it.getString("name"), it.getString("host"), it.getInt("port"), it.getString("token"))
            }
        } catch (_: Exception) { null }
    }

    companion object {
        const val CH_PLAYER = "player"
        const val CH_EVENTS = "pc_events"
        const val ID_PLAYER = 1
        const val ID_CONNECTED = 2
        const val ID_EVENT_BASE = 1000
        const val ACTION_STOP = "com.kirdev.pulsepc.STOP"
        const val ACTION_TOGGLE = "com.kirdev.pulsepc.TOGGLE"
        const val ACTION_NEXT = "com.kirdev.pulsepc.NEXT"
        const val ACTION_PREV = "com.kirdev.pulsepc.PREV"
        const val ACTION_VOL_UP = "com.kirdev.pulsepc.VOL_UP"
        const val ACTION_VOL_DOWN = "com.kirdev.pulsepc.VOL_DOWN"

        fun start(context: Context) {
            context.startForegroundService(Intent(context, PulseService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, PulseService::class.java))
        }
    }
}
