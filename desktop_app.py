import os
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_IMAGE = os.path.join(BASE_DIR, "uploads", "images")
UPLOAD_VIDEO = os.path.join(BASE_DIR, "uploads", "videos")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DB_PATH = os.path.join(DATA_DIR, "models.sqlite3")
MODEL_CODE_PREFIX = "MT"


BASIC_FIELDS = [
    ("model_code", "编号"),
    ("name", "姓名"),
    ("gender", "性别"),
    ("age", "年龄"),
    ("phone", "电话"),
    ("hair_length", "发长"),
    ("hair_color", "发色"),
    ("tags", "标签"),
    ("note", "备注"),
    ("image", "图片"),
    ("video", "视频"),
]

FEMALE_FIELDS = [
    ("female_hair_perm_3y", "3年内烫过次数", "text"),
    ("female_hair_dye_3y", "3年内染过次数", "text"),
    ("female_hair_gradient", "是否挑染", "yesno"),
    ("female_hair_dye_type", "染过颜色类型", "text"),
    ("female_hair_bleach", "是否漂过", "yesno"),
    ("female_hair_straight", "是否拉直/柔顺/软化", "yesno"),
    ("female_accept_dye", "接受染发", "yesno"),
    ("female_accept_perm", "接受烫发", "yesno"),
    ("female_accept_bleach", "接受漂发", "yesno"),
    ("female_hair_hardness", "发质", ["适中", "细软", "粗硬"]),
    ("female_hair_curl", "是否自然卷", "yesno"),
    ("female_hair_cut", "最多修剪位置", ["充胸", "锁骨", "下巴"]),
    ("female_hair_iron", "常用夹板/电棒", "yesno"),
    ("female_hair_root_perm", "是否烫发根", "yesno"),
    ("female_hair_protein", "是否蛋白矫正", "yesno"),
    ("female_hair_self_dye", "是否自己染发", "yesno"),
    ("female_height_weight", "身高体重", "text"),
    ("female_free_time", "空余时间", "text"),
    ("female_last_perm_dye", "上次烫染时间", "text"),
]

MALE_FIELDS = [
    ("male_hair_perm", "目前是否烫过", "yesno"),
    ("male_hair_dye", "目前是否染过", "yesno"),
    ("male_hair_curl", "是否自然卷", "yesno"),
    ("male_hair_hardness", "发质", ["细软", "粗硬"]),
    ("male_height_weight", "身高体重", "text"),
    ("male_last_perm_dye", "上次烫染时间", "text"),
    ("male_free_time", "日常空余时间", "text"),
]

ALL_COLUMNS = [
    "id",
    "model_code",
    "name",
    "gender",
    "age",
    "phone",
    "hair_length",
    "hair_color",
    "tags",
    "note",
    "image",
    "video",
    *[field for field, _, _ in FEMALE_FIELDS],
    *[field for field, _, _ in MALE_FIELDS],
]


def ensure_dirs():
    for path in (DATA_DIR, UPLOAD_IMAGE, UPLOAD_VIDEO, DOWNLOAD_DIR):
        os.makedirs(path, exist_ok=True)


def init_db():
    ensure_dirs()
    columns = ", ".join(
        ["id INTEGER PRIMARY KEY AUTOINCREMENT", "model_code TEXT UNIQUE"]
        + [f"{name} TEXT" for name in ALL_COLUMNS if name not in ("id", "model_code")]
    )
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"CREATE TABLE IF NOT EXISTS models ({columns})")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(models)")}
        for column in ALL_COLUMNS:
            if column not in existing and column != "id":
                conn.execute(f"ALTER TABLE models ADD COLUMN {column} TEXT")
        conn.commit()


def fetch_models(filters=None):
    filters = filters or {}
    where = []
    params = []

    keyword = filters.get("keyword", "").strip()
    if keyword:
        where.append("(name LIKE ? OR tags LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    gender = filters.get("gender", "")
    if gender:
        where.append("gender = ?")
        params.append(gender)

    age_range = filters.get("age_range", "")
    if age_range == "≤30":
        where.append("CAST(age AS INTEGER) <= 30")
    elif age_range == "＞30":
        where.append("CAST(age AS INTEGER) > 30")

    for field, _, kind in FEMALE_FIELDS + MALE_FIELDS:
        value = filters.get(field, "").strip()
        if not value:
            continue
        if kind == "text":
            where.append(f"{field} LIKE ?")
            params.append(f"%{value}%")
        else:
            where.append(f"{field} = ?")
            params.append(value)

    sql = f"SELECT {', '.join(ALL_COLUMNS)} FROM models"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_model(model_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT {', '.join(ALL_COLUMNS)} FROM models WHERE id = ?", (model_id,)
        ).fetchone()
        return dict(row) if row else None


def copy_media(source_path, target_dir):
    if not source_path:
        return ""
    safe_name = os.path.basename(source_path)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    target_path = os.path.join(target_dir, f"{timestamp}_{safe_name}")
    shutil.copy2(source_path, target_path)
    return os.path.relpath(target_path, BASE_DIR)


def create_model(data):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT MAX(id) FROM models")
        next_id = (cursor.fetchone()[0] or 0) + 1
        data["model_code"] = f"{MODEL_CODE_PREFIX}{datetime.now().strftime('%Y%m%d')}{next_id:03d}"
        fields = [column for column in ALL_COLUMNS if column != "id"]
        values = [data.get(field, "") for field in fields]
        placeholders = ", ".join(["?"] * len(fields))
        conn.execute(
            f"INSERT INTO models ({', '.join(fields)}) VALUES ({placeholders})", values
        )
        conn.commit()


def value(model, key):
    return model.get(key) or "无"


def build_info_text(model):
    base_info = f"""【基础资料】
编号：{value(model, 'model_code')}
姓名：{value(model, 'name')}
性别：{value(model, 'gender')}
年龄：{value(model, 'age')}
电话：{value(model, 'phone')}
发长：{value(model, 'hair_length')}
发色：{value(model, 'hair_color')}
标签：{value(model, 'tags')}
备注：{value(model, 'note')}
"""
    if model.get("gender") == "女":
        lines = ["", "【女模发质询问表（仅限现有头发）】"]
        for index, (field, label, _) in enumerate(FEMALE_FIELDS, start=1):
            lines.append(f"{index}. {label}：{value(model, field)}")
        return base_info + "\n".join(lines) + "\n"
    if model.get("gender") == "男":
        lines = ["", "【男模发质询问表（仅限现有头发）】", "注意：男模需要接受剪烫染"]
        for index, (field, label, _) in enumerate(MALE_FIELDS, start=1):
            lines.append(f"{index}. {label}：{value(model, field)}")
        return base_info + "\n".join(lines) + "\n"
    return base_info


def export_models(model_ids, zip_path):
    selected = [get_model(model_id) for model_id in model_ids]
    selected = [model for model in selected if model]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for model in selected:
            folder_name = f"{value(model, 'model_code')}_{value(model, 'name')}"
            zip_file.writestr(f"{folder_name}/完整资料.txt", build_info_text(model))
            for media_key in ("image", "video"):
                media_path = model.get(media_key)
                if not media_path:
                    continue
                absolute_path = os.path.join(BASE_DIR, media_path)
                if os.path.exists(absolute_path):
                    zip_file.write(absolute_path, f"{folder_name}/{os.path.basename(media_path)}")


class AddModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增模特")
        self.resize(760, 720)
        self.inputs = {}
        self.image_path = ""
        self.video_path = ""

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form_layout = QVBoxLayout(content)

        base_group = QGroupBox("基础资料")
        base_form = QFormLayout(base_group)
        self.inputs["name"] = QLineEdit()
        self.inputs["gender"] = QComboBox()
        self.inputs["gender"].addItems(["", "女", "男"])
        self.inputs["age"] = QLineEdit()
        self.inputs["phone"] = QLineEdit()
        self.inputs["hair_length"] = QLineEdit()
        self.inputs["hair_color"] = QLineEdit()
        self.inputs["tags"] = QLineEdit()
        self.inputs["note"] = QTextEdit()
        base_form.addRow("姓名（艺名）", self.inputs["name"])
        base_form.addRow("性别", self.inputs["gender"])
        base_form.addRow("年龄", self.inputs["age"])
        base_form.addRow("电话", self.inputs["phone"])
        base_form.addRow("发长", self.inputs["hair_length"])
        base_form.addRow("发色", self.inputs["hair_color"])
        base_form.addRow("标签（多个用逗号分隔）", self.inputs["tags"])
        base_form.addRow("备注", self.inputs["note"])

        media_layout = QHBoxLayout()
        image_button = QPushButton("选择图片")
        video_button = QPushButton("选择视频")
        self.image_label = QLabel("未选择")
        self.video_label = QLabel("未选择")
        image_button.clicked.connect(self.choose_image)
        video_button.clicked.connect(self.choose_video)
        media_layout.addWidget(image_button)
        media_layout.addWidget(self.image_label)
        media_layout.addWidget(video_button)
        media_layout.addWidget(self.video_label)
        base_form.addRow("媒体文件", media_layout)
        form_layout.addWidget(base_group)

        self.female_group = self.create_field_group("女模发质询问表", FEMALE_FIELDS)
        self.male_group = self.create_field_group("男模发质询问表（男模需要接受剪烫染）", MALE_FIELDS)
        form_layout.addWidget(self.female_group)
        form_layout.addWidget(self.male_group)

        buttons = QHBoxLayout()
        save_button = QPushButton("保存")
        cancel_button = QPushButton("取消")
        save_button.clicked.connect(self.save)
        cancel_button.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        form_layout.addLayout(buttons)

        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.inputs["gender"].currentTextChanged.connect(self.toggle_gender_fields)
        self.toggle_gender_fields()

    def create_field_group(self, title, fields):
        group = QGroupBox(title)
        grid = QGridLayout(group)
        for index, (field, label, kind) in enumerate(fields):
            widget = self.create_input(kind)
            self.inputs[field] = widget
            grid.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            grid.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        return group

    def create_input(self, kind):
        if kind == "text":
            return QLineEdit()
        combo = QComboBox()
        combo.addItem("")
        combo.addItems(["是", "否"] if kind == "yesno" else kind)
        return combo

    def toggle_gender_fields(self):
        gender = self.inputs["gender"].currentText()
        self.female_group.setVisible(gender == "女")
        self.male_group.setVisible(gender == "男")

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)"
        )
        if path:
            self.image_path = path
            self.image_label.setText(os.path.basename(path))

    def choose_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "", "Videos (*.mp4 *.mov *.avi *.mkv);;All Files (*)"
        )
        if path:
            self.video_path = path
            self.video_label.setText(os.path.basename(path))

    def read_widget(self, widget):
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QTextEdit):
            return widget.toPlainText().strip()
        return widget.text().strip()

    def save(self):
        if not self.inputs["name"].text().strip():
            QMessageBox.warning(self, "提示", "请填写姓名。")
            return
        if not self.inputs["gender"].currentText():
            QMessageBox.warning(self, "提示", "请选择性别。")
            return

        data = {field: "" for field in ALL_COLUMNS if field != "id"}
        for field, widget in self.inputs.items():
            data[field] = self.read_widget(widget)
        data["image"] = copy_media(self.image_path, UPLOAD_IMAGE) if self.image_path else ""
        data["video"] = copy_media(self.video_path, UPLOAD_VIDEO) if self.video_path else ""
        create_model(data)
        self.accept()


class DetailDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{value(model, 'name')} - 详情")
        self.resize(860, 680)

        layout = QHBoxLayout(self)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumWidth(280)
        image_label.setText("暂无图片")
        image_path = model.get("image")
        if image_path:
            absolute_path = os.path.join(BASE_DIR, image_path)
            pixmap = QPixmap(absolute_path)
            if not pixmap.isNull():
                image_label.setPixmap(pixmap.scaled(280, 520, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(image_label)

        text = QTextEdit()
        text.setReadOnly(True)
        video_line = f"\n视频文件：{model.get('video')}\n" if model.get("video") else ""
        text.setPlainText(build_info_text(model) + video_line)
        layout.addWidget(text, 1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("模特资料管理系统")
        self.resize(1180, 760)
        self.models = []
        self.filter_inputs = {}
        self.setup_ui()
        self.load_models()

    def setup_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        add_button = QPushButton("新增模特")
        detail_button = QPushButton("查看详情")
        export_button = QPushButton("导出选中资料")
        refresh_button = QPushButton("刷新")
        add_button.clicked.connect(self.add_model)
        detail_button.clicked.connect(self.show_selected_detail)
        export_button.clicked.connect(self.export_selected)
        refresh_button.clicked.connect(self.load_models)
        toolbar.addWidget(add_button)
        toolbar.addWidget(detail_button)
        toolbar.addWidget(export_button)
        toolbar.addStretch()
        toolbar.addWidget(refresh_button)
        main_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.create_filter_panel())
        splitter.addWidget(self.create_table())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def create_filter_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(330)
        panel = QWidget()
        layout = QVBoxLayout(panel)

        basic_group = QGroupBox("基础筛选")
        basic_form = QFormLayout(basic_group)
        self.filter_inputs["keyword"] = QLineEdit()
        self.filter_inputs["gender"] = QComboBox()
        self.filter_inputs["gender"].addItems(["", "女", "男"])
        self.filter_inputs["age_range"] = QComboBox()
        self.filter_inputs["age_range"].addItems(["", "≤30", "＞30"])
        basic_form.addRow("标签/姓名", self.filter_inputs["keyword"])
        basic_form.addRow("性别", self.filter_inputs["gender"])
        basic_form.addRow("年龄", self.filter_inputs["age_range"])
        layout.addWidget(basic_group)

        tabs = QTabWidget()
        tabs.addTab(self.create_filter_group(FEMALE_FIELDS), "女模发质")
        tabs.addTab(self.create_filter_group(MALE_FIELDS), "男模发质")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        search_button = QPushButton("搜索")
        reset_button = QPushButton("重置")
        search_button.clicked.connect(self.load_models)
        reset_button.clicked.connect(self.reset_filters)
        buttons.addWidget(search_button)
        buttons.addWidget(reset_button)
        layout.addLayout(buttons)
        layout.addStretch()

        scroll.setWidget(panel)
        return scroll

    def create_filter_group(self, fields):
        group = QWidget()
        form = QFormLayout(group)
        for field, label, kind in fields:
            widget = AddModelDialog.create_input(self, kind)
            self.filter_inputs[field] = widget
            form.addRow(label, widget)
        return group

    def create_table(self):
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "编号", "姓名", "性别", "年龄", "电话", "标签"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.doubleClicked.connect(self.show_selected_detail)
        self.table.setColumnHidden(0, True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        return self.table

    def read_filters(self):
        filters = {}
        for field, widget in self.filter_inputs.items():
            if isinstance(widget, QComboBox):
                filters[field] = widget.currentText()
            else:
                filters[field] = widget.text().strip()
        return filters

    def reset_filters(self):
        for widget in self.filter_inputs.values():
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            else:
                widget.clear()
        self.load_models()

    def load_models(self):
        self.models = fetch_models(self.read_filters())
        self.table.clearContents()
        self.table.setRowCount(len(self.models))
        for row, model in enumerate(self.models):
            values = [
                model.get("id"),
                model.get("model_code"),
                model.get("name"),
                model.get("gender"),
                model.get("age"),
                model.get("phone"),
                model.get("tags"),
            ]
            for column, item_value in enumerate(values):
                item = QTableWidgetItem(str(item_value or ""))
                if column == 0:
                    item.setData(Qt.UserRole, model.get("id"))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        if self.models:
            self.table.selectRow(0)
        self.statusBar().showMessage(f"共 {len(self.models)} 条资料")

    def selected_model_ids(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        ids = []
        for row in rows:
            if 0 <= row < len(self.models):
                ids.append(int(self.models[row]["id"]))
        return ids

    def add_model(self):
        dialog = AddModelDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.clear_filters()
            self.load_models()
            QMessageBox.information(self, "完成", "模特资料已保存。")

    def show_selected_detail(self):
        ids = self.selected_model_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先选择一条资料。")
            return
        model = get_model(ids[0])
        if model:
            DetailDialog(model, self).exec_()

    def export_selected(self):
        ids = self.selected_model_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先选择要导出的资料。")
            return
        default_name = f"模特资料_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存导出文件", os.path.join(DOWNLOAD_DIR, default_name), "Zip Files (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        export_models(ids, path)
        QMessageBox.information(self, "完成", f"已导出到：\n{path}")

    def clear_filters(self):
        for widget in self.filter_inputs.values():
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            else:
                widget.clear()


def main():
    init_db()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
