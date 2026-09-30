"""Desktop editor for Telegram features, with no credentials or OS actions."""
from copy import deepcopy
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QLineEdit, QCheckBox, QSpinBox, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QDialogButtonBox)

from modules.bot_preferences import load_preferences, save_preferences, validate_preferences, FAVORITE_ACTIONS

OPTIONS_STYLE = """
QTabWidget::pane { border: 1px solid #253349; }
QTabBar::tab { background: #16202C; padding: 10px; }
QTabBar::tab:selected { background: #1F4E85; }
QListWidget { background: #0D1319; border: 1px solid #253349; border-radius: 8px; }
QListWidget::item { padding: 7px; }
QListWidget::item:selected { background: #12263D; }
QListWidget::indicator { width: 16px; height: 16px; border: 1px solid #4C6A90; border-radius: 4px; background: #0D1319; }
QListWidget::indicator:checked { background: #2A8CFF; border-color: #2A8CFF; }
QSpinBox { background: #16202C; padding: 6px; border-radius: 6px; }
"""


class BotOptionsDialog(QDialog):
    def __init__(self, programs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Возможности Telegram-бота")
        self.setStyleSheet((parent.styleSheet() if parent else "") + OPTIONS_STYLE)
        self.resize(710, 680)
        self.setMinimumSize(580, 580)
        self.options = load_preferences()
        self.programs = {p.get("id", str(i)): p for i, p in enumerate(programs)}
        self.scenarios = deepcopy(self.options["scenarios"])
        self.edit_id = None
        self.draft_dirty = False
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        self.build_panel()
        self.build_scenarios()
        self.build_alerts()
        self.message = QLabel("Изменения применятся без перезапуска после сохранения.")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        controls.accepted.connect(self.save)
        controls.rejected.connect(self.reject)
        outer.addWidget(controls)

    def tab(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        self.tabs.addTab(widget, title)
        return layout

    def build_panel(self):
        layout = self.tab("Панель и избранное")
        form = QFormLayout()
        self.device_name = QLineEdit(self.options["device_name"])
        self.device_name.setMaxLength(80)
        self.device_name.setPlaceholderText("По умолчанию — имя компьютера")
        self.greeting = QLineEdit(self.options["greeting"])
        self.greeting.setMaxLength(300)
        form.addRow("Имя ПК", self.device_name)
        form.addRow("Приветствие", self.greeting)
        layout.addLayout(form)
        self.panel_checks = {}
        row = QHBoxLayout()
        for key, title in (("show_device", "Имя ПК"), ("show_time", "Время"), ("show_programs", "Число программ"), ("show_tips", "Подсказки")):
            checkbox = QCheckBox(title)
            checkbox.setChecked(self.options[key])
            self.panel_checks[key] = checkbox
            row.addWidget(checkbox)
        layout.addLayout(row)
        layout.addWidget(QLabel("Избранное на главной панели Telegram — до 6 действий"))
        self.favorites = QListWidget()
        for key, title in FAVORITE_ACTIONS.items():
            self.add_choice(self.favorites, title, key, key in self.options["favorites"])
        for key, program in self.programs.items():
            self.add_choice(self.favorites, "Программа: " + program["name"], "program:" + key, "program:" + key in self.options["favorites"])
        layout.addWidget(self.favorites)

    @staticmethod
    def add_choice(widget, title, key, checked=False):
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        widget.addItem(item)

    @staticmethod
    def checked(widget):
        return [widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(widget.count())
                if widget.item(i).checkState() == Qt.CheckState.Checked]

    def build_scenarios(self):
        layout = self.tab("Сценарии")
        self.scenario_list = QListWidget()
        self.scenario_list.setMaximumHeight(130)
        layout.addWidget(self.scenario_list)
        self.reload_scenarios()
        controls = QHBoxLayout()
        for title, callback in (("Новый", self.new_scenario), ("Изменить выбранный", self.edit_scenario), ("Удалить выбранный", self.delete_scenario)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.scenario_name = QLineEdit()
        self.scenario_name.setMaxLength(50)
        self.scenario_name.setPlaceholderText("Название, например «Работа»")
        self.scenario_name.textChanged.connect(self.mark_draft)
        layout.addWidget(self.scenario_name)
        layout.addWidget(QLabel("Программы запускаются в порядке этого списка."))
        self.scenario_programs = QListWidget()
        for key, program in self.programs.items():
            self.add_choice(self.scenario_programs, program["name"], key)
        self.scenario_programs.itemChanged.connect(self.mark_draft)
        layout.addWidget(self.scenario_programs)
        button = QPushButton("Добавить / применить сценарий")
        button.clicked.connect(self.apply_scenario)
        layout.addWidget(button)
        hint = QLabel("Сначала добавьте и сохраните программы в основном окне. Можно создать до 20 сценариев.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def mark_draft(self, *_):
        self.draft_dirty = True

    def reload_scenarios(self):
        self.scenario_list.clear()
        for scenario in self.scenarios:
            item = QListWidgetItem(scenario["name"])
            item.setData(Qt.ItemDataRole.UserRole, scenario["id"])
            self.scenario_list.addItem(item)

    def keep_draft(self):
        return not self.draft_dirty or self.apply_scenario()

    def new_scenario(self):
        if not self.keep_draft():
            return
        self.edit_id = None
        self.scenario_name.clear()
        for i in range(self.scenario_programs.count()):
            self.scenario_programs.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.draft_dirty = False

    def edit_scenario(self):
        item = self.scenario_list.currentItem()
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not self.keep_draft():
            return
        scenario = next(s for s in self.scenarios if s["id"] == key)
        self.edit_id = key
        self.scenario_name.setText(scenario["name"])
        for i in range(self.scenario_programs.count()):
            entry = self.scenario_programs.item(i)
            entry.setCheckState(Qt.CheckState.Checked if entry.data(Qt.ItemDataRole.UserRole) in scenario["program_ids"] else Qt.CheckState.Unchecked)
        self.draft_dirty = False

    def delete_scenario(self):
        item = self.scenario_list.currentItem()
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        self.scenarios = [s for s in self.scenarios if s["id"] != key]
        if self.edit_id == key:
            self.draft_dirty = False
            self.new_scenario()
        self.reload_scenarios()

    def apply_scenario(self):
        candidate = dict(id=self.edit_id or uuid.uuid4().hex, name=self.scenario_name.text().strip(),
                         program_ids=self.checked(self.scenario_programs))
        scenarios = [s for s in self.scenarios if s["id"] != candidate["id"]] + [candidate]
        try:
            validate_preferences({**self.options, "scenarios": scenarios})
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        self.scenarios = scenarios
        self.edit_id = candidate["id"]
        self.draft_dirty = False
        self.reload_scenarios()
        self.message.setText("Сценарий подготовлен. Нажмите «Сохранить» внизу окна.")
        return True

    def build_alerts(self):
        layout = self.tab("Уведомления")
        settings = self.options["alerts"]
        self.alert_checks = {}
        for key, title in (("enabled", "Включить уведомления"), ("cpu_enabled", "Длительная нагрузка CPU"), ("disk_enabled", "Мало места на дисках")):
            checkbox = QCheckBox(title)
            checkbox.setChecked(settings[key])
            self.alert_checks[key] = checkbox
            layout.addWidget(checkbox)
        form = QFormLayout()
        self.alert_numbers = {}
        for key, title, low, high, suffix in (
            ("cpu_percent", "Порог CPU", 1, 100, " %"),
            ("cpu_seconds", "Длительность нагрузки", 10, 3600, " с"),
            ("disk_free_gb", "Остаток места меньше", 1, 1000, " ГБ"),
            ("interval_seconds", "Проверять каждые", 5, 300, " с"),
            ("cooldown_minutes", "Пауза между повторами", 1, 1440, " мин"),
        ):
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setSuffix(suffix)
            spin.setValue(settings[key])
            self.alert_numbers[key] = spin
            form.addRow(title, spin)
        self.processes = QLineEdit(", ".join(settings["processes"]))
        self.processes.setPlaceholderText("obs64.exe, notepad.exe")
        form.addRow("Следить за завершением", self.processes)
        layout.addLayout(form)
        hint = QLabel("До 20 имён процессов через запятую. Сообщение приходит, когда работающая программа завершилась. Уведомления действуют, пока запущен бот.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def save(self):
        if not self.keep_draft():
            self.tabs.setCurrentIndex(1)
            return
        value = deepcopy(self.options)
        value.update(device_name=self.device_name.text().strip(), greeting=self.greeting.text().strip(),
                     favorites=self.checked(self.favorites), scenarios=self.scenarios)
        value.update({key: widget.isChecked() for key, widget in self.panel_checks.items()})
        value["alerts"].update({key: widget.isChecked() for key, widget in self.alert_checks.items()})
        value["alerts"].update({key: widget.value() for key, widget in self.alert_numbers.items()})
        value["alerts"]["processes"] = list(dict.fromkeys(p.strip().lower() for p in self.processes.text().split(",") if p.strip()))
        try:
            save_preferences(value)
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))
            return
        self.accept()
