package com.kirdev.pulsepc

import android.app.AlertDialog
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.slider.Slider
import com.google.android.material.tabs.TabLayout
import android.widget.ArrayAdapter
import android.widget.ListView
import org.json.JSONArray
import org.json.JSONObject
import java.net.Inet4Address
import java.util.concurrent.atomic.AtomicInteger

/** Запомненный ПК. Токен получен при первом подтверждении на самом ПК. */
data class SavedPc(val name: String, val host: String, val port: Int, val token: String)

class MainActivity : AppCompatActivity() {
    private var api: PcApi? = null
    private lateinit var tabViews: List<View>
    private var scanning = false
    private val volumeStep = 1 // одно нажатие клавиши громкости Windows = 2%
    private var monitorCount = 0
    private var monitor = 0
    private var filesPath = ""
    private var filesParent = ""
    private var failures = 0
    private var currentPcName = ""
    private val online = HashMap<String, Boolean>()
    private var seeking = false
    private var audioCoverKey = "?"

    private val prefs by lazy { getSharedPreferences("pulse", Context.MODE_PRIVATE) }
    private val poll = object : Runnable {
        override fun run() {
            if (api != null && v<View>(R.id.controlPanel).visibility == View.VISIBLE) refresh(silent = true)
            Bg.postDelayed(this, 2000)
        }
    }
    private val pickFile = registerForActivityResult(ActivityResultContracts.GetContent()) { uri -> uri?.let { uploadFile(it) } }

    private fun <T : View> v(id: Int): T = findViewById(id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        v<MaterialButton>(R.id.refreshBtn).setOnClickListener { refreshAll() }
        v<MaterialButton>(R.id.disconnectBtn).setOnClickListener { showPcList() }

        setupTabs()
        setupControls()
        renderSaved()
        refreshAll()

        // Вернуться к последнему ПК без лишних нажатий.
        val last = prefs.getString("last", null)
        loadPcs().firstOrNull { it.name == last }?.let { connect(it) }
    }

    override fun onResume() {
        super.onResume()
        Bg.postDelayed(poll, 1000)
    }

    override fun onPause() {
        super.onPause()
        Bg.removeCallbacks(poll)
    }

    // ---------- Сохранённые ПК ----------

    private fun loadPcs(): List<SavedPc> = try {
        val arr = JSONArray(prefs.getString("pcs", "[]"))
        (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            SavedPc(o.getString("name"), o.getString("host"), o.getInt("port"), o.getString("token"))
        }
    } catch (_: Exception) {
        emptyList()
    }

    private fun storePcs(list: List<SavedPc>) {
        val arr = JSONArray()
        list.forEach { arr.put(JSONObject().put("name", it.name).put("host", it.host).put("port", it.port).put("token", it.token)) }
        prefs.edit().putString("pcs", arr.toString()).apply()
    }

    private fun savePc(pc: SavedPc) {
        storePcs(loadPcs().filter { it.name != pc.name } + pc)
        prefs.edit().putString("last", pc.name).apply()
    }

    private fun forgetPc(pc: SavedPc) {
        storePcs(loadPcs().filter { it.name != pc.name })
        if (prefs.getString("last", null) == pc.name) prefs.edit().remove("last").apply()
        renderSaved()
    }

    // ---------- Список ПК / подключение ----------

    /** Уведомления плеера и ПК работают, пока подключён ПК (и когда приложение закрыто). */
    private fun startNotifications() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        PulseService.start(this)
    }

    private fun showPcList() {
        PulseService.stop(this)
        Bg.removeCallbacks(audioPoll)
        api = null
        prefs.edit().remove("last").apply()
        v<View>(R.id.controlPanel).visibility = View.GONE
        v<View>(R.id.connectPanel).visibility = View.VISIBLE
        renderSaved()
        refreshAll()
    }

    /** Список «Мои ПК»: счётчик, у каждого ПК — в сети он или нет. */
    private fun renderSaved() {
        val list = v<LinearLayout>(R.id.savedList)
        list.removeAllViews()
        val pcs = loadPcs()
        val onlineCount = pcs.count { online[it.name] == true }
        v<TextView>(R.id.savedTitle).text =
            if (pcs.isEmpty()) "МОИ ПК · 0" else "МОИ ПК · ${pcs.size}   ·   В СЕТИ: $onlineCount"
        v<View>(R.id.savedEmpty).visibility = if (pcs.isEmpty()) View.VISIBLE else View.GONE
        pcs.forEach { pc ->
            val state = online[pc.name]
            val (sub, color) = when (state) {
                true -> "● В сети · ${pc.host}" to 0xFF19C3FF.toInt()
                false -> "○ Не в сети · ${pc.host}" to 0xFF8A97A8.toInt()
                else -> "… Проверка · ${pc.host}" to 0xFF8A97A8.toInt()
            }
            val card = pcCard(list, pc.name, sub) { connect(pc) }
            card.findViewById<TextView>(R.id.pcSub).setTextColor(color)
            card.alpha = if (state == false) 0.65f else 1f
            card.setOnLongClickListener {
                confirm("Забыть ${pc.name}?") { forgetPc(pc) }
                true
            }
            list.addView(card)
        }
    }

    /** Кнопка «обновить»: заново проверяет сохранённые ПК и ищет новые. */
    private fun refreshAll() {
        v<View>(R.id.refreshBtn).animate().rotationBy(360f).setDuration(600).start()
        checkSaved()
        scan()
    }

    private fun checkSaved() {
        val pcs = loadPcs()
        online.clear()
        renderSaved()
        pcs.forEach { pc ->
            Bg.submit {
                val alive = PcApi.ping(pc.host, pc.port, 1200) == pc.name
                Bg.post {
                    online[pc.name] = alive
                    if (v<View>(R.id.connectPanel).visibility == View.VISIBLE) renderSaved()
                }
            }
        }
    }

    private fun pcCard(parent: LinearLayout, title: String, sub: String, onClick: () -> Unit): View {
        val card = layoutInflater.inflate(R.layout.item_pc, parent, false)
        card.findViewById<TextView>(R.id.pcTitle).text = title
        card.findViewById<TextView>(R.id.pcSub).text = sub
        card.setOnClickListener { onClick() }
        return card
    }

    private fun message(text: String) { v<TextView>(R.id.connectError).text = text }

    /** Подключение к сохранённому ПК. Если токен устарел — сопряжение заново. */
    private fun connect(pc: SavedPc) {
        message("Подключение к ${pc.name}…")
        val candidate = PcApi(pc.host, pc.port, pc.token)
        Bg.run({ candidate.getJson("/api/status") }, {
            when {
                it is ApiException && it.code == 401 -> pair(pc.name, pc.host, pc.port)
                it is ApiException -> message(it.message ?: "Ошибка")
                else -> {
                    message("${pc.name} недоступен. ПК включён, Pulse PC запущен, одна Wi‑Fi сеть?")
                    showBanner("ПК недоступен", pc.name)
                }
            }
        }) { status ->
            val saved = pc.copy(name = status.optString("name", pc.name))
            savePc(saved)
            message("")
            api = candidate
            currentPcName = saved.name
            showControl(status)
            startNotifications()
            showBanner("Подключено", "Вы управляете ПК ${saved.name}")
        }
    }

    /** Первое подключение: владелец ПК подтверждает запрос в окне на ПК. */
    /** ПК недоступен: разделы закрываются, на экране выбора он помечен «не в сети». */
    private fun connectionLost() {
        val name = currentPcName.ifEmpty { "ПК" }
        showPcList()
        message("ПК недоступен. Запустите Pulse PC на компьютере и обновите список.")
        showBanner("ПК недоступен", "Связь с $name потеряна")
    }

    private fun pair(name: String, host: String, port: Int) {
        message("Подтвердите подключение в окне на ПК «$name»…")
        val device = Build.MODEL ?: "Телефон"
        Bg.run({ PcApi.pair(host, port, device) }, {
            message(when {
                it is ApiException -> it.message ?: "Ошибка"
                else -> "Нет ответа от ПК. Проверьте, что бот запущен."
            })
        }) { json ->
            connect(SavedPc(json.optString("name", name), host, port, json.getString("token")))
        }
    }

    private fun showControl(status: JSONObject) {
        v<View>(R.id.connectPanel).visibility = View.GONE
        v<View>(R.id.controlPanel).visibility = View.VISIBLE
        v<TextView>(R.id.pcName).text = status.optString("name", "ПК")
        failures = 0
        v<BottomNavigationView>(R.id.bottomNav).selectedItemId = R.id.nav_home
        showPage(R.id.pageHome)
        applyStatus(status)
        loadPrograms()
        loadMonitors()
        filesPath = ""
        v<LinearLayout>(R.id.filesList).removeAllViews()
    }

    // ---------- Поиск ПК в сети ----------

    private fun wifiPrefix(): String? {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val props = cm.getLinkProperties(cm.activeNetwork) ?: return null
        val addr = props.linkAddresses.map { it.address }.firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
            ?: return null
        return addr.hostAddress?.substringBeforeLast('.')
    }

    private fun scan() {
        if (scanning) return
        val status = v<TextView>(R.id.scanStatus)
        val list = v<LinearLayout>(R.id.foundList)
        list.removeAllViews()
        val prefix = wifiPrefix()
        if (prefix == null) {
            status.text = "Нет Wi‑Fi подключения."
            return
        }
        scanning = true
        status.text = "Ищу ПК с Pulse PC…"
        // Сначала быстрый автопоиск: ПК сам откликается на широковещательный запрос.
        Bg.submit {
            val hits = PcApi.discover(prefix)
            Bg.post {
                hits.forEach { (name, host, port) -> onFound(list, name, host, port) }
                if (hits.isNotEmpty()) finishScan(status, list) else scanSubnet(prefix, status, list)
            }
        }
    }

    private fun finishScan(status: TextView, list: LinearLayout) {
        scanning = false
        status.text = if (list.childCount == 0) "Новых ПК не найдено. Pulse PC запущен на ПК?" else "Найдены новые ПК:"
    }

    /** Запасной вариант, если роутер глушит широковещательные пакеты. */
    private fun scanSubnet(prefix: String, status: TextView, list: LinearLayout) {
        status.text = "Проверяю сеть $prefix.0/24…"
        val left = AtomicInteger(254)
        for (i in 1..254) {
            Bg.submit {
                val ip = "$prefix.$i"
                val name = PcApi.ping(ip, 8765, 600)
                Bg.post {
                    if (name != null) onFound(list, name, ip, 8765)
                    if (left.decrementAndGet() == 0) finishScan(status, list)
                }
            }
        }
    }

    private fun onFound(list: LinearLayout, name: String, ip: String, port: Int) {
        val known = loadPcs().firstOrNull { it.name == name }
        if (known != null) {
            // ПК уже сохранён: если сменился IP — обновляем молча.
            if (known.host != ip) {
                storePcs(loadPcs().map { if (it.name == name) it.copy(host = ip, port = port) else it })
            }
            online[name] = true
            renderSaved()
            return
        }
        list.addView(pcCard(list, name, "$ip · нажмите, чтобы подключиться") { pair(name, ip, port) })
    }

    // ---------- Вкладки и нижнее меню ----------

    private fun setupTabs() {
        // Внутри «Программ»: программы, сценарии, окна.
        tabViews = listOf(R.id.tabPrograms, R.id.tabScenarios, R.id.tabWindows).map { v<View>(it) }
        val tabs = v<TabLayout>(R.id.appTabs)
        listOf("Программы", "Сценарии", "Окна").forEach { tabs.addTab(tabs.newTab().setText(it)) }
        tabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                tabViews.forEachIndexed { i, view -> view.visibility = if (i == tab.position) View.VISIBLE else View.GONE }
                loadAppTab(tab.position)
            }
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })

        // Нижняя панель: все разделы, видна только при подключённом ПК.
        v<BottomNavigationView>(R.id.bottomNav).setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_home -> { showPage(R.id.pageHome); refresh() }
                R.id.nav_apps -> { showPage(R.id.pageApps); loadAppTab(tabs.selectedTabPosition.coerceAtLeast(0)) }
                R.id.nav_files -> { showPage(R.id.pageFiles); if (filesPath.isEmpty()) loadRoots() }
                R.id.nav_audio -> showPage(R.id.pageAudio)
                R.id.nav_screen -> showPage(R.id.pageScreen)
            }
            true
        }
    }

    private fun loadAppTab(position: Int) = when (position) {
        0 -> loadPrograms()
        1 -> loadScenarios()
        else -> loadWindows()
    }

    private fun showPage(id: Int) {
        listOf(R.id.pageHome, R.id.pageApps, R.id.pageFiles, R.id.pageAudio, R.id.pageScreen)
            .forEach { v<View>(it).visibility = if (it == id) View.VISIBLE else View.GONE }
        Bg.removeCallbacks(audioPoll)
        if (id == R.id.pageAudio) audioPoll.run()
    }

    // ---------- Плеер ----------

    private val audioPoll = object : Runnable {
        override fun run() {
            val client = api
            if (client != null && v<View>(R.id.pageAudio).visibility == View.VISIBLE) {
                Bg.run({ client.getJson("/api/player/state").optJSONObject("player") ?: JSONObject() }, { },
                    { if (api === client) applyPlayer(it) })
                Bg.postDelayed(this, 1500)
            }
        }
    }

    private fun playerCommand(name: String, value: Double? = null) {
        send("/api/player/$name", if (value != null) JSONObject().put("value", value) else null) {
            Bg.postDelayed({ if (v<View>(R.id.pageAudio).visibility == View.VISIBLE) audioPoll.run() }, 300)
        }
    }

    /** Идентификатор приложения Windows → понятное название. */
    private fun prettySource(id: String): String {
        val known = mapOf(
            "ru.yandex.desktop.music" to "Яндекс Музыка", "spotify" to "Spotify", "chrome" to "Chrome",
            "msedge" to "Edge", "firefox" to "Firefox", "vlc" to "VLC", "yandexbrowser" to "Яндекс Браузер",
            "zunemusic" to "Медиаплеер", "microsoft.media.player" to "Медиаплеер")
        val lower = id.lowercase()
        known.entries.firstOrNull { lower.contains(it.key) }?.let { return it.value }
        return id.substringAfterLast('.').replaceFirstChar { it.uppercase() }
    }

    private fun clock(seconds: Double): String {
        val s = seconds.toInt().coerceAtLeast(0)
        return "%d:%02d".format(s / 60, s % 60)
    }

    private fun applyPlayer(p: JSONObject) {
        val status = p.optString("status", "none")
        v<TextView>(R.id.trackTitle).apply {
            text = if (status == "none") "Ничего не играет" else p.optString("title").ifEmpty { "Без названия" }
            isSelected = true // запускает бегущую строку
        }
        v<TextView>(R.id.trackArtist).text = if (status == "none") "Запустите музыку на ПК или выберите трек ниже" else p.optString("artist")
        v<TextView>(R.id.trackSource).apply {
            text = prettySource(p.optString("source"))
            visibility = if (status == "none" || text.isNullOrEmpty()) View.GONE else View.VISIBLE
        }
        v<MaterialButton>(R.id.mediaPlay).setIconResource(if (status == "playing") R.drawable.ic_pause else R.drawable.ic_play)
        val duration = p.optDouble("duration", 0.0)
        val slider = v<Slider>(R.id.trackSeek)
        slider.isEnabled = duration > 0
        slider.valueTo = duration.coerceAtLeast(1.0).toFloat()
        if (!seeking) slider.value = p.optDouble("position", 0.0).coerceIn(0.0, slider.valueTo.toDouble()).toFloat()
        v<TextView>(R.id.trackElapsed).text = clock(if (seeking) slider.value.toDouble() else p.optDouble("position", 0.0))
        v<TextView>(R.id.trackTotal).text = clock(duration)

        val key = p.optString("cover")
        if (key != audioCoverKey) {
            audioCoverKey = key
            val image = v<ImageView>(R.id.coverImage)
            if (key.isEmpty()) {
                image.setImageResource(R.drawable.ic_music); image.alpha = 0.5f; image.setPadding(dp(72), dp(72), dp(72), dp(72))
            } else {
                val client = api ?: return
                Bg.run({ client.getBytes("/api/player/cover?key=" + java.net.URLEncoder.encode(key, "UTF-8")) }, { }) { bytes ->
                    if (key == audioCoverKey) {
                        image.setPadding(0, 0, 0, 0); image.alpha = 1f
                        image.setImageBitmap(BitmapFactory.decodeByteArray(bytes, 0, bytes.size))
                    }
                }
            }
        }
    }

    /** Список музыки из библиотеки плеера Pulse PC; выбранный трек играет на ПК. */
    private fun openLibrary() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/player/tracks") }, { toast(it.message) }) { json ->
            val arr = json.optJSONArray("tracks") ?: JSONArray()
            val all = (0 until arr.length()).map { arr.getJSONObject(it) }
            val dialog = BottomSheetDialog(this)
            val box = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(16), dp(16), dp(16), dp(16))
            }
            if (all.isEmpty()) {
                box.addView(TextView(this).apply {
                    text = "Библиотека пуста. Добавьте папки с музыкой на вкладке «Плеер» в Pulse PC на ПК."
                    setTextColor(0xFF8A97A8.toInt()); setPadding(0, dp(8), 0, dp(16))
                })
            } else {
                val search = EditText(this).apply { hint = "Поиск по трекам"; setSingleLine() }
                val list = ListView(this).apply { layoutParams = LinearLayout.LayoutParams(-1, dp(420)) }
                var shown = all
                val adapter = ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, ArrayList())
                fun fill() {
                    val q = search.text.toString().trim().lowercase()
                    shown = all.filter { q.isEmpty() || it.optString("title").lowercase().contains(q) || it.optString("folder").lowercase().contains(q) }
                    adapter.clear()
                    adapter.addAll(shown.map { "${it.optString("title")}\n${it.optString("folder")}" })
                }
                search.addTextChangedListener(object : android.text.TextWatcher {
                    override fun afterTextChanged(s: android.text.Editable?) = fill()
                    override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                    override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
                })
                list.adapter = adapter
                list.setOnItemClickListener { _, _, position, _ ->
                    val path = shown[position].optString("path")
                    send("/api/player/tracks/open", JSONObject().put("path", path)) {
                        toast("Играет на ПК")
                        dialog.dismiss()
                        Bg.postDelayed({ audioPoll.run() }, 800)
                    }
                }
                fill()
                box.addView(search)
                box.addView(list)
            }
            dialog.setContentView(box)
            dialog.show()
        }
    }

    // ---------- Команды ----------

    /** Баннер с логотипом поверх экрана; исчезает сам. */
    private fun showBanner(title: String, text: String) {
        val banner = v<View>(R.id.banner)
        v<TextView>(R.id.bannerTitle).text = title
        v<TextView>(R.id.bannerText).text = text
        banner.removeCallbacks(hideBanner)
        banner.alpha = 0f
        banner.translationY = -dp(24).toFloat()
        banner.visibility = View.VISIBLE
        banner.animate().alpha(1f).translationY(0f).setDuration(220).start()
        banner.postDelayed(hideBanner, 3200)
    }

    private val hideBanner = Runnable {
        val banner = v<View>(R.id.banner)
        banner.animate().alpha(0f).translationY(-dp(24).toFloat()).setDuration(220)
            .withEndAction { banner.visibility = View.GONE }.start()
    }

    private fun toast(text: String?) = Toast.makeText(this, text ?: "Ошибка", Toast.LENGTH_SHORT).show()

    private fun send(path: String, body: JSONObject? = null, done: (JSONObject) -> Unit = {}) {
        val client = api ?: return
        Bg.run({ client.postJson(path, body) }, { toast(it.message) }) { done(it) }
    }

    private fun confirm(text: String, action: () -> Unit) {
        MaterialAlertDialogBuilder(this).setMessage(text)
            .setPositiveButton("Да") { _, _ -> action() }
            .setNegativeButton("Отмена", null).show()
    }

    private fun media(action: String, count: Int = 1) =
        send("/api/media/$action", JSONObject().put("count", count))

    private fun setupControls() {
        v<MaterialButton>(R.id.lockBtn).setOnClickListener { send("/api/system/lock") { toast("ПК заблокирован") } }
        v<MaterialButton>(R.id.sleepBtn).setOnClickListener { confirm("Отправить ПК в сон?") { send("/api/system/sleep") } }
        v<MaterialButton>(R.id.restartBtn).setOnClickListener { askMinutes("restart", "Перезагрузка") }
        v<MaterialButton>(R.id.shutdownBtn).setOnClickListener { askMinutes("shutdown", "Выключение") }
        v<MaterialButton>(R.id.cancelPowerBtn).setOnClickListener {
            send("/api/system/cancel") { toast(it.optString("message")); refresh() }
        }
        v<MaterialButton>(R.id.closeActive).setOnClickListener {
            confirm("Закрыть активное окно на ПК?") { send("/api/system/close_active") }
        }

        v<MaterialButton>(R.id.mediaPrev).setOnClickListener { playerCommand("prev") }
        v<MaterialButton>(R.id.mediaPlay).setOnClickListener { playerCommand("toggle") }
        v<MaterialButton>(R.id.mediaNext).setOnClickListener { playerCommand("next") }
        v<MaterialButton>(R.id.libraryBtn).setOnClickListener { openLibrary() }
        v<Slider>(R.id.trackSeek).addOnSliderTouchListener(object : Slider.OnSliderTouchListener {
            override fun onStartTrackingTouch(slider: Slider) { seeking = true }
            override fun onStopTrackingTouch(slider: Slider) {
                seeking = false
                playerCommand("seek", slider.value.toDouble())
            }
        })
        v<MaterialButton>(R.id.volMute).setOnClickListener { media("mute") }
        v<MaterialButton>(R.id.volDown).setOnClickListener { media("voldown", 1) }
        v<MaterialButton>(R.id.volUp).setOnClickListener { media("volup", 1) }

        v<MaterialButton>(R.id.shotBtn).setOnClickListener { screenshot() }
        v<MaterialButton>(R.id.monitorBtn).setOnClickListener {
            monitor = (monitor + 1) % (monitorCount + 1)
            (it as MaterialButton).text = monitorLabel()
        }
        v<MaterialButton>(R.id.openUrlBtn).setOnClickListener {
            val url = v<EditText>(R.id.urlInput).text.toString().trim()
            if (url.isNotEmpty()) send("/api/open_url", JSONObject().put("url", url)) { toast("Открыто на ПК") }
        }
        v<MaterialButton>(R.id.searchBtn).setOnClickListener {
            val query = v<EditText>(R.id.searchInput).text.toString().trim()
            if (query.isNotEmpty()) send("/api/search", JSONObject().put("query", query)) { toast("Поиск открыт на ПК") }
        }

        v<MaterialButton>(R.id.filesUp).setOnClickListener { if (filesParent.isNotEmpty()) loadDir(filesParent) else loadRoots() }
        v<MaterialButton>(R.id.filesUpload).setOnClickListener { pickFile.launch("*/*") }
        v<MaterialButton>(R.id.filesHistory).setOnClickListener { showHistory() }
    }

    private fun askMinutes(action: String, title: String) {
        val input = EditText(this).apply { setText("1"); inputType = android.text.InputType.TYPE_CLASS_NUMBER }
        MaterialAlertDialogBuilder(this).setTitle("$title через (мин)").setView(input)
            .setPositiveButton("Запустить") { _, _ ->
                val minutes = input.text.toString().toIntOrNull() ?: return@setPositiveButton
                send("/api/system/$action", JSONObject().put("minutes", minutes)) {
                    toast("Таймер запущен"); refresh()
                }
            }.setNegativeButton("Отмена", null).show()
    }

    // ---------- Данные ----------

    private fun refresh(silent: Boolean = false) {
        val client = api ?: return
        Bg.run({ client.getJson("/api/status", 2500) }, {
            if (api !== client) return@run
            if (!silent) toast(it.message)
            val gone = it is java.net.ConnectException || it is java.net.UnknownHostException ||
                it is java.net.NoRouteToHostException
            // ПК закрыл Pulse PC или пропал из сети: сразу отключаемся.
            if (it !is ApiException && (gone || ++failures >= 2)) connectionLost()
        }) {
            if (api === client) { failures = 0; applyStatus(it) }
        }
    }

    private fun applyStatus(status: JSONObject) {
        v<TextView>(R.id.pcState).text = if (status.optBoolean("locked")) "● Заблокирован — управление недоступно" else "● Онлайн"
        val box = v<LinearLayout>(R.id.statsBox)
        box.removeAllViews()
        status.optString("info").lines().filter { it.isNotBlank() }.forEachIndexed { i, line ->
            // «Диск C:\ — свободно …» делим по тире, остальное — по «: ».
            val sep = if (line.contains(" — ")) " — " else ": "
            val title = line.substringBefore(sep).trim()
            val value = if (line.contains(sep)) line.substringAfter(sep).trim() else ""
            box.addView(TextView(this).apply {
                text = title; textSize = 13f; setTextColor(0xFF8A97A8.toInt())
                if (i > 0) setPadding(0, dp(14), 0, 0)
            })
            box.addView(TextView(this).apply {
                text = value.ifEmpty { title }; textSize = 18f; setTextColor(0xFFFFFFFF.toInt())
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            })
            // Проценты (процессор, память) показываем полосой.
            Regex("(\\d{1,3})%").find(value)?.let { m ->
                if (title.startsWith("Процессор") || title.startsWith("Оперативная")) {
                    box.addView(LinearProgressIndicator(this).apply {
                        max = 100; progress = m.groupValues[1].toInt().coerceIn(0, 100)
                        trackCornerRadius = dp(4); trackThickness = dp(6)
                        setIndicatorColor(0xFF2A8CFF.toInt()); trackColor = 0xFF1B2635.toInt()
                        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) }
                    })
                }
            }
        }
        val power = status.optJSONObject("power")
        v<TextView>(R.id.powerText).text =
            if (power != null) "⏱ ${if (power.optString("action") == "restart") "Перезагрузка" else "Выключение"} через ${power.optInt("seconds") / 60 + 1} мин" else ""
        v<View>(R.id.cancelPowerBtn).visibility = if (power != null) View.VISIBLE else View.GONE
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun loadPrograms() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/programs") }, { toast(it.message) }) { json ->
            val list = v<LinearLayout>(R.id.programsList)
            list.removeAllViews()
            val items = json.optJSONArray("programs")
            v<View>(R.id.programsEmpty).visibility = if (items == null || items.length() == 0) View.VISIBLE else View.GONE
            for (i in 0 until (items?.length() ?: 0)) {
                val p = items!!.getJSONObject(i)
                list.addView(row(p.optString("name"),
                    "Запустить" to { send("/api/programs/${p.optString("id")}/run") { toast("Запущено") } },
                    "Закрыть" to { confirm("Закрыть ${p.optString("name")}?") { send("/api/programs/${p.optString("id")}/kill") } }))
            }
        }
    }

    private fun loadScenarios() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/scenarios") }, { toast(it.message) }) { json ->
            val list = v<LinearLayout>(R.id.scenariosList)
            list.removeAllViews()
            val items = json.optJSONArray("scenarios")
            v<View>(R.id.scenariosEmpty).visibility = if (items == null || items.length() == 0) View.VISIBLE else View.GONE
            for (i in 0 until (items?.length() ?: 0)) {
                val s = items!!.getJSONObject(i)
                list.addView(row("${s.optString("name")}  ·  программ: ${s.optInt("count")}",
                    "Запустить сценарий" to {
                        send("/api/scenarios/${s.optString("id")}/run") { toast(it.optString("message")) }
                    }))
            }
        }
    }

    private fun loadWindows() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/windows") }, { toast(it.message) }) { json ->
            val list = v<LinearLayout>(R.id.windowsList)
            list.removeAllViews()
            val items = json.optJSONArray("windows") ?: return@run
            for (i in 0 until items.length()) {
                val w = items.getJSONObject(i)
                val base = "/api/windows/${w.optLong("hwnd")}"
                list.addView(row(w.optString("title"),
                    "Вперёд" to { send("$base/focus") },
                    "Свернуть" to { send("$base/min") },
                    "Закрыть" to { confirm("Закрыть «${w.optString("title")}»?") { send("$base/close") { loadWindows() } } }))
            }
        }
    }

    // ---------- Файлы ----------

    private fun loadRoots() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/files/roots") }, { toast(it.message) }) { json ->
            filesPath = ""
            filesParent = ""
            v<TextView>(R.id.filesPath).text = "Выберите место"
            val list = v<LinearLayout>(R.id.filesList)
            list.removeAllViews()
            val roots = json.optJSONArray("roots") ?: return@run
            for (i in 0 until roots.length()) {
                val r = roots.getJSONObject(i)
                list.addView(fileRow(R.drawable.ic_folder, r.optString("name"), "") { loadDir(r.optString("path")) })
            }
        }
    }

    private fun loadDir(path: String) {
        val client = api ?: return
        Bg.run({ client.getJson("/api/files/list?path=" + java.net.URLEncoder.encode(path, "UTF-8")) }, { toast(it.message) }) { json ->
            filesPath = json.optString("path")
            filesParent = json.optString("parent")
            v<TextView>(R.id.filesPath).text = filesPath
            val list = v<LinearLayout>(R.id.filesList)
            list.removeAllViews()
            val items = json.optJSONArray("items") ?: return@run
            if (items.length() == 0) list.addView(fileRow(R.drawable.ic_file, "Папка пуста", "") {})
            for (i in 0 until items.length()) {
                val f = items.getJSONObject(i)
                val full = filesPath.trimEnd('\\') + "\\" + f.optString("name")
                if (f.optBoolean("dir")) {
                    list.addView(fileRow(R.drawable.ic_folder, f.optString("name"), "") { loadDir(full) })
                } else {
                    list.addView(fileRow(R.drawable.ic_file, f.optString("name"), formatSize(f.optLong("size"))) {
                        confirm("Скачать «${f.optString("name")}» на телефон?") { downloadFile(full, f.optString("name")) }
                    })
                }
            }
        }
    }

    private fun formatSize(bytes: Long): String = when {
        bytes >= 1 shl 30 -> "%.1f ГБ".format(bytes / 1073741824.0)
        bytes >= 1 shl 20 -> "%.1f МБ".format(bytes / 1048576.0)
        bytes >= 1 shl 10 -> "%.0f КБ".format(bytes / 1024.0)
        else -> "$bytes Б"
    }

    private fun downloadFile(pcPath: String, name: String) {
        val client = api ?: return
        toast("Скачиваю…")
        Bg.run({
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/PulsePC")
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: throw ApiException("Не удалось создать файл")
            try {
                contentResolver.openOutputStream(uri)!!.use { client.download(pcPath, it) }
            } catch (e: Exception) {
                contentResolver.delete(uri, null, null)
                throw e
            }
            uri
        }, { toast(it.message) }) { uri ->
            showBanner("Файл скачан", name)
            notifyDownloaded(name, uri)
        }
    }

    /** Уведомление с логотипом: файл скачан, по нажатию открывается. */
    private fun notifyDownloaded(name: String, uri: Uri) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
        nm.createNotificationChannel(android.app.NotificationChannel(
            PulseService.CH_EVENTS, "Уведомления с ПК", android.app.NotificationManager.IMPORTANCE_DEFAULT))
        val open = android.app.PendingIntent.getActivity(this, name.hashCode(),
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, contentResolver.getType(uri) ?: "*/*")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT)
        val note = android.app.Notification.Builder(this, PulseService.CH_EVENTS)
            .setSmallIcon(R.drawable.ic_stat_pulse)
            .setColor(0xFF2A8CFF.toInt())
            .setLargeIcon(BitmapFactory.decodeResource(resources, R.drawable.logo_emblem))
            .setContentTitle("Файл скачан")
            .setContentText(name)
            .setSubText("Загрузки/PulsePC")
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        nm.notify(3000 + (name.hashCode() and 0xFFF), note)
    }

    private fun uploadFile(uri: Uri) {
        val client = api ?: return
        val name = contentResolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(c.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME)) else null
        } ?: "file"
        toast("Отправляю на ПК…")
        Bg.run({ contentResolver.openInputStream(uri)!!.use { client.upload(name, it) } }, { toast(it.message) }) { toast(it) }
    }

    private fun showHistory() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/history") }, { toast(it.message) }) { json ->
            val items = json.optJSONArray("history") ?: JSONArray()
            val text = if (items.length() == 0) "Передач ещё не было." else (0 until minOf(items.length(), 30)).joinToString("\n\n") {
                val h = items.getJSONObject(it)
                val dir = if (h.optString("direction") == "incoming") "⬇ на ПК" else "⬆ с ПК"
                "${h.optString("time").replace('T', ' ')}\n$dir · ${h.optString("name")} · ${h.optString("status")}"
            }
            MaterialAlertDialogBuilder(this).setTitle("История файлов").setMessage(text).setPositiveButton("Закрыть", null).show()
        }
    }

    // ---------- Экран ----------

    private fun loadMonitors() {
        val client = api ?: return
        Bg.run({ client.getJson("/api/monitors") }, { }) { json ->
            monitorCount = json.optInt("count")
            monitor = 0
            val btn = v<MaterialButton>(R.id.monitorBtn)
            btn.visibility = if (monitorCount > 1) View.VISIBLE else View.GONE
            btn.text = monitorLabel()
        }
    }

    private fun monitorLabel() = if (monitor == 0) "Экран: все мониторы" else "Экран: монитор $monitor"

    private fun screenshot() {
        val client = api ?: return
        val btn = v<MaterialButton>(R.id.shotBtn)
        btn.isEnabled = false
        btn.text = "Загрузка…"
        Bg.run({ client.getBytes("/api/screenshot?width=1280&monitor=${if (monitorCount > 1) monitor else 1}") }, {
            btn.isEnabled = true; btn.text = "Сделать скриншот"; toast(it.message)
        }) { bytes ->
            btn.isEnabled = true; btn.text = "Сделать скриншот"
            v<ImageView>(R.id.shotImage).setImageBitmap(BitmapFactory.decodeByteArray(bytes, 0, bytes.size))
            v<View>(R.id.shotCard).visibility = View.VISIBLE
        }
    }

    // ---------- Общие элементы ----------

    private fun card(): MaterialCardView = MaterialCardView(this).apply {
        setCardBackgroundColor(0xFF0D1319.toInt())
        radius = dp(20).toFloat()
        cardElevation = 0f
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(10) }
    }

    /** Строка файла или папки. */
    private fun fileRow(iconRes: Int, title: String, sub: String, onClick: () -> Unit = {}): View {
        val line = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(14))
        }
        line.addView(ImageView(this).apply {
            setImageResource(iconRes); alpha = 0.85f
            layoutParams = LinearLayout.LayoutParams(dp(24), dp(24)).apply { marginEnd = dp(16) }
        })
        val texts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
        }
        texts.addView(TextView(this).apply {
            text = title; textSize = 15f; setTextColor(0xFFFFFFFF.toInt()); maxLines = 2
        })
        if (sub.isNotEmpty()) texts.addView(TextView(this).apply {
            text = sub; textSize = 12f; setTextColor(0xFF8A97A8.toInt())
        })
        line.addView(texts)
        return card().apply {
            isClickable = true; isFocusable = true
            setOnClickListener { onClick() }
            addView(line)
        }
    }

    /** Карточка с названием и рядом кнопок действий. */
    private fun row(title: String, vararg actions: Pair<String, () -> Unit>): View {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(10))
        }
        box.addView(TextView(this).apply {
            text = title; textSize = 16f; setTextColor(0xFFFFFFFF.toInt()); maxLines = 2
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        })
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        actions.forEach { (label, action) ->
            buttons.addView((layoutInflater.inflate(R.layout.btn_outline, buttons, false) as MaterialButton).apply {
                text = label; minHeight = 0; minimumHeight = 0; textSize = 13f
                layoutParams = LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = dp(6) }
                setOnClickListener { action() }
            })
        }
        box.addView(buttons)
        return card().apply { addView(box) }
    }
}
