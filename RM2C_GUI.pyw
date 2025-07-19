import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox,
    QPushButton, QLabel, QGroupBox, QGridLayout, QRadioButton,
    QButtonGroup, QPlainTextEdit
)
from PyQt5.QtCore import Qt, QProcess
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QFontDatabase, QFont, QIcon

from RM2CData import Num2Name

class RomDrop(QLabel):
    def __init__(self):
        super().__init__("Drop ROM here")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border: 1px dashed gray; padding: 10px")
        self.rom_path = ''

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            file_path = event.mimeData().urls()[0].toLocalFile()
            self.setText(os.path.basename(file_path))
            self.rom_path = os.path.basename(file_path)

class RM2CGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RM2CAT")
        self.setMinimumSize(600, 800)
        self.setMaximumSize(600, 800)

        layout = QVBoxLayout()
        self.setLayout(layout)

        top_layout = QHBoxLayout()
        self.rom_drop = RomDrop()
        top_layout.addWidget(self.rom_drop)

        mode_group = QButtonGroup(self)
        self.rom_manager_btn = QRadioButton("ROM Manager")
        self.sm64_editor_btn = QRadioButton("SM64 Editor")
        self.rom_manager_btn.setChecked(True)
        mode_group.addButton(self.rom_manager_btn)
        mode_group.addButton(self.sm64_editor_btn)

        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self.rom_manager_btn)
        mode_layout.addWidget(self.sm64_editor_btn)
        top_layout.addLayout(mode_layout)

        layout.addLayout(top_layout)

        export_group = QGroupBox("Export Options")
        export_layout = QGridLayout()
        self.checks = {}
        opts = ["text", "misc", "textures", "actors", "objects", "skip texture lut gbi"]
        for i, opt in enumerate(opts):
            cb = QCheckBox(opt.capitalize())
            self.checks[opt] = cb
            export_layout.addWidget(cb, i // 2, i % 2)
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        level_group = QGroupBox("Levels")
        level_layout = QVBoxLayout()
        level_buttons_layout = QHBoxLayout()

        self.all_cb = QCheckBox("All")
        select_all = QPushButton("Select All")
        unselect_all = QPushButton("Unselect All")

        level_buttons_layout.addWidget(self.all_cb)
        level_buttons_layout.addStretch()
        level_buttons_layout.addWidget(select_all)
        level_buttons_layout.addWidget(unselect_all)

        level_layout.addLayout(level_buttons_layout)

        grid = QGridLayout()
        self.level_checkboxes = []
        for idx, (num, name) in enumerate(Num2Name.items()):
            cb = QCheckBox(name)
            self.level_checkboxes.append((cb, num))
            grid.addWidget(cb, idx // 4, idx % 4)

        level_layout.addLayout(grid)
        level_group.setLayout(level_layout)
        layout.addWidget(level_group)

        select_all.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in self.level_checkboxes])
        unselect_all.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in self.level_checkboxes])
        self.all_cb.clicked.connect(lambda: [cb.setChecked(self.all_cb.isChecked()) for cb, _ in self.level_checkboxes])

        self.run_btn = QPushButton("Run RM2C")
        self.run_btn.setFixedHeight(40)
        layout.addWidget(self.run_btn)
        self.run_btn.clicked.connect(self.run_rm2c)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: white; color: black;")
        layout.addWidget(self.log_output)

        self.process = None

    def run_rm2c(self):
        rom = self.rom_drop.rom_path
        if not rom:
            self.status_label.setText("Please select a ROM.")
            return

        args = ["python", "-u", "RM2C.py", f"rom={rom}"]

        levels = [lid for cb, lid in self.level_checkboxes if cb.isChecked()]
        args.append(f"levels={levels}")

        if self.sm64_editor_btn.isChecked():
            args.append("editor=True")

        if self.checks.get("actors") and self.checks["actors"].isChecked():
            args.append("actors=all")
        if self.checks.get("objects") and self.checks["objects"].isChecked():
            args.append("Objects=all")
        if self.checks.get("skip texture lut gbi") and self.checks["skip texture lut gbi"].isChecked():
            args.append("skipTLUT=True")

        for key in ["Text", "Misc", "Textures"]:
            if self.checks.get(key.lower()) and self.checks[key.lower()].isChecked():
                args.append(f"{key}=1")

        self.status_label.setText("Running...")
        print(args)
        self.log_output.clear()

        self.process = QProcess(self)
        self.process.setProgram("python")
        self.process.setArguments(args[1:])
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)
        self.process.start()

    def handle_stdout(self):
        try:
            data = self.process.readAllStandardOutput().data().decode()
            self.log_output.appendPlainText(data)
        except:
            pass

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode()
        self.log_output.appendPlainText("[ERROR] " + data)

    def process_finished(self):
        if self.process.exitStatus() == QProcess.NormalExit and self.process.exitCode() == 0:
            self.status_label.setText("Done.")
        else:
            self.status_label.setText("Error occurred. See logs.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    font_id = QFontDatabase.addApplicationFont("gui/sm64.ttf")
    app.setWindowIcon(QIcon("gui/icon.png"))
    if font_id == -1:
        print("Failed to load font!")
    else:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            custom_font_family = families[0]
            font = QFont(custom_font_family, 10)
            app.setFont(font)
        else:
            pass
    window = RM2CGUI()
    window.show()
    sys.exit(app.exec_())