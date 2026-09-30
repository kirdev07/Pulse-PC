"""Audio player of the Pulse PC window. Commands arrive from the window and from
the phone (through modules.player_bridge); playback state is published back."""
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer

from modules import player_bridge


class PlayerController(QObject):
    command = Signal(str, object)   # (name, value) — safe to emit from any thread
    changed = Signal()              # state changed, window refreshes its widgets

    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.5)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.queue = []
        self.index = -1
        self.cover = None
        self.cover_key = ""
        self.command.connect(self.handle, Qt.ConnectionType.QueuedConnection)
        self.player.playbackStateChanged.connect(lambda _: self.publish())
        self.player.metaDataChanged.connect(self.read_metadata)
        self.player.durationChanged.connect(lambda _: self.publish())
        self.player.mediaStatusChanged.connect(self.media_status)
        self.player.errorOccurred.connect(lambda *_: self.publish())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.publish)
        self.timer.start(700)
        player_bridge.CONTROLLER = self

    # ----- commands -----
    def handle(self, name, value=None):
        if name == "open":
            self.open_track(str(value))
        elif name == "toggle":
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()
        elif name == "play":
            self.player.play()
        elif name == "pause":
            self.player.pause()
        elif name == "stop":
            self.player.stop()
            self.index = -1
        elif name == "next":
            self.step(1)
        elif name == "prev":
            # Like most players: restart the track first, go back only near its start.
            if self.player.position() > 3000:
                self.player.setPosition(0)
            else:
                self.step(-1)
        elif name == "seek":
            self.player.setPosition(int(float(value) * 1000))
        elif name == "volume":
            self.audio.setVolume(max(0.0, min(1.0, float(value))))
        self.publish()

    def open_track(self, path, queue=None):
        self.queue = queue if queue is not None else player_bridge.scan_tracks()
        paths = [t["path"] for t in self.queue]
        self.index = paths.index(path) if path in paths else -1
        if self.index < 0:
            self.queue = [{"path": path, "title": Path(path).stem}]
            self.index = 0
        self.load_current()

    def load_current(self):
        track = self.queue[self.index]
        self.cover, self.cover_key = None, ""
        self.player.setSource(QUrl.fromLocalFile(track["path"]))
        self.player.play()

    def step(self, offset):
        if not self.queue:
            return
        self.index = (self.index + offset) % len(self.queue)
        self.load_current()

    def media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.step(1)
        self.publish()

    # ----- state -----
    def read_metadata(self):
        data = self.player.metaData()
        image = data.value(QMediaMetaData.Key.CoverArtImage) or data.value(QMediaMetaData.Key.ThumbnailImage)
        self.cover = None
        if isinstance(image, QImage) and not image.isNull():
            image = image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "JPEG", 85)
            self.cover = bytes(buffer.data())
        self.cover_key = f"own:{self.index}:{len(self.cover or b'')}"
        self.publish()

    def current_title(self):
        data = self.player.metaData()
        title = data.stringValue(QMediaMetaData.Key.Title)
        if not title and 0 <= self.index < len(self.queue):
            title = self.queue[self.index]["title"]
        return title or ""

    def publish(self):
        state = self.player.playbackState()
        has_track = 0 <= self.index < len(self.queue)
        status = {QMediaPlayer.PlaybackState.PlayingState: "playing",
                  QMediaPlayer.PlaybackState.PausedState: "paused"}.get(state, "stopped")
        data = self.player.metaData()
        title = self.current_title() if has_track else ""
        artist = (data.stringValue(QMediaMetaData.Key.ContributingArtist) or "") if has_track else ""
        if has_track and not artist and " - " in title:     # file named "Artist - Title" without tags
            artist, title = (part.strip() for part in title.split(" - ", 1))
        with player_bridge.LOCK:
            player_bridge.STATE.update(
                active=has_track and status in ("playing", "paused"),
                title=title,
                artist=artist,
                album=(data.stringValue(QMediaMetaData.Key.AlbumTitle) or "") if has_track else "",
                status=status, position=self.player.position() / 1000.0,
                duration=self.player.duration() / 1000.0, volume=self.audio.volume(),
                cover=self.cover, cover_key=self.cover_key)
        self.changed.emit()
