import os
# 设置环境变量，有时可减少 macOS 下的相关警告
os.environ["QT_MAC_WANTS_LAYER"] = "1"

import warnings
# 屏蔽类似 “IMKCFRunLoopWakeUpReliable” 的警告（该警告不会影响功能）
warnings.filterwarnings("ignore", message=".*IMKCFRunLoopWakeUpReliable.*")

import sys
import requests
import re
import time
import json
import random
from datetime import datetime
import pytz
from urllib.parse import unquote

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGroupBox, QMessageBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem, QAbstractItemView
)
from PyQt5.QtCore import QTimer, QDateTime, QThread, pyqtSignal, Qt

# 如果使用 Selenium 自动抓取 token，则需要安装 Selenium 和 ChromeDriver
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

#############################################
# 全局变量，用于缓存上一次成功的 token
#############################################
current_token = None
# 用于记录用户手动切换的模式
# manual_session_type 为 None 表示自动判断，否则 0 表示白天模式，1 表示夜盘模式
manual_session_type = None

# ==================== API配置 ====================
EXCHANGE_RATE_KEY = "9be1d1309bdcd99529c2b9af"  # 离岸人民币汇率 API Key

# ==================== 全局数据容器 ====================
current_data = {
    "cnh_rate": 0.0  # 美元兑离岸人民币汇率
}

#############################################
# 获取离岸人民币汇率
#############################################
def get_cnh_rate():
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_KEY}/latest/USD"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get("result") == "success":
            rate = float(data["conversion_rates"]["CNY"])
            current_data["cnh_rate"] = rate
            print(f"当前离岸人民币汇率: {rate}")
            return rate
        else:
            print("获取离岸人民币汇率数据失败")
            return None
    except Exception as e:
        print(f"离岸人民币汇率获取失败: {str(e)}")
        return None

#############################################
# 数据抓取相关函数
#############################################
def get_contract_data(code):
    """
    根据合约代码调用接口，返回 (合约名称, 当前价格, 更新时间)
    """
    url = "https://api.jijinhao.com/sQuoteCenter/realTime.htm"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"),
        "Referer": "https://quote.cngold.org/"
    }
    timestamp = int(time.time() * 1000)
    params = {"code": code, "_": timestamp}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
    except Exception as e:
        return None, None, None

    if response.status_code == 200:
        match = re.search(r'var hq_str = "(.*?)";', response.text)
        if match:
            data = match.group(1)
            fields = data.split(',')
            try:
                contract_name = fields[0]
                price = float(fields[3])  # 第4个字段为价格
                update_time = f"{fields[-3]} {fields[-2]}"
                return contract_name, price, update_time
            except (IndexError, ValueError):
                return None, None, None
    return None, None, None

def get_hk_time():
    """获取精确到毫秒的香港时间"""
    return datetime.now(pytz.timezone('Asia/Hong_Kong'))

def generate_anti_params():
    """生成反爬虫参数"""
    timestamp = int(time.time() * 1000)
    return {
        'qid': str(timestamp),
        '_': str(timestamp),
        'callback': f'jQuery{random.randint(10**15, 10**16-1)}_{timestamp}'
    }

def fetch_latest_token_selenium():
    """
    使用 Selenium 自动提取 token。
    避免抓取到包含 "+" 的无效 token。
    """
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print("Selenium 初始化失败：", str(e))
        return None

    try:
        url = "https://www.hkex.com.hk/products/listed-derivatives/foreign-exchange/usd-cnh-futures?sc_lang=zh-hk#&product=CUS"
        driver.get(url)
        time.sleep(5)
        logs = driver.get_log("performance")
        token = None
        for entry in logs:
            message = entry.get("message")
            try:
                log = json.loads(message)
                request = log.get("message", {}).get("params", {}).get("request", {})
                req_url = request.get("url", "")
                if "getderivativesfutures?lang=chi&token=" in req_url:
                    m = re.search(r"token=([^&]+)", req_url)
                    if m:
                        token_candidate = m.group(1)
                        token_candidate = unquote(token_candidate)
                        if '+' in token_candidate:
                            print("跳过包含 '+' 的 token:", token_candidate)
                            continue
                        token = token_candidate
                        break
            except Exception:
                continue
        driver.quit()
        if token:
            print("自动获取到最新 token：", token)
        else:
            print("未能通过 Selenium 提取 token")
        return token
    except Exception as e:
        driver.quit()
        print("Selenium 抓取 token 出错：", str(e))
        return None

def fetch_latest_token():
    """优先使用 Selenium 方法获取 token"""
    if SELENIUM_AVAILABLE:
        token = fetch_latest_token_selenium()
        return token
    else:
        print("Selenium 不可用，无法自动更新 token")
        return None

def get_exchange_rate_data():
    """
    获取港交所汇率数据，返回字典 { con_l: se }。
    若用户手动设置汇率模式则优先使用，否则根据香港时间自动判断：
      - 工作日 7:00～19:00 使用白天汇率（type=0），其余时段（夜盘）使用夜盘汇率（type=1）
      - 周末默认使用白天汇率（type=0）
    """
    global current_token, manual_session_type
    headers = {
        'User-Agent': ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"),
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.hkex.com.hk/?sc_lang=zh-HK',
        'Origin': 'https://www.hkex.com.hk',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'Connection': 'keep-alive'
    }
    
    with requests.Session() as s:
        s.get('https://www.hkex.com.hk/', headers=headers, timeout=10)
        s.get('https://www1.hkex.com.hk/hkexwidget/apis/seccheck.jsp', headers=headers, timeout=10)
        
        hk_time = get_hk_time()
        if manual_session_type is not None:
            session_type = manual_session_type
        else:
            if hk_time.weekday() in [5, 6]:
                session_type = 0
            else:
                session_type = 0 if (hk_time.hour >= 7 and hk_time.hour < 19) else 1

        token_to_use = current_token
        if not token_to_use:
            for i in range(10):
                token = fetch_latest_token()
                if token:
                    token_to_use = token
                    current_token = token
                    break
            if not token_to_use:
                token_to_use = "evLtsLsBNAUVTPxtGqVeG48hg9MAP9GxfF1kuI/d08jNXxWPutx3Ph6ilmoLDZjw"
                current_token = token_to_use
                print("未能自动获取 token，使用默认 token")
        
        params = {
            'lang': 'chi',
            'token': token_to_use,
            'ats': 'CUS',
            'type': session_type
        }
        params.update(generate_anti_params())
        
        base_url = "https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures"
        query = '&'.join([f"{k}={v}" for k, v in params.items()])
        final_url = f"{base_url}?{query}"
        response = s.get(final_url, headers=headers, timeout=15)
        
        try:
            text = response.text.strip()
            if text.startswith("jQuery"):
                json_str = text.split('(', 1)[1].rsplit(')', 1)[0]
                data = json.loads(json_str)
            else:
                data = response.json()
            if 'data' not in data or 'futureslist' not in data['data'] or not data['data']['futureslist']:
                raise ValueError("无效数据结构")
            rate_dict = {}
            for item in data['data']['futureslist']:
                try:
                    rate_value = float(item['se'])
                except:
                    rate_value = 1.0
                rate_dict[item['con_l']] = rate_value
            return rate_dict
        except Exception as e:
            print("使用 token 刷新汇率数据失败，尝试重新获取 token...", str(e))
            for attempt in range(10):
                new_token = fetch_latest_token()
                if new_token:
                    current_token = new_token
                    params['token'] = new_token
                    query = '&'.join([f"{k}={v}" for k, v in params.items()])
                    final_url = f"{base_url}?{query}"
                    response = s.get(final_url, headers=headers, timeout=15)
                    try:
                        text = response.text.strip()
                        if text.startswith("jQuery"):
                            json_str = text.split('(', 1)[1].rsplit(')', 1)[0]
                            data = json.loads(json_str)
                        else:
                            data = response.json()
                        if 'data' in data and 'futureslist' in data['data'] and data['data']['futureslist']:
                            rate_dict = {}
                            for item in data['data']['futureslist']:
                                try:
                                    rate_value = float(item['se'])
                                except:
                                    rate_value = 1.0
                                rate_dict[item['con_l']] = rate_value
                            print("刷新汇率数据成功，使用新 token")
                            return rate_dict
                    except Exception as inner_e:
                        print(f"第 {attempt+1} 次尝试失败：", inner_e)
                        continue
            raise Exception("尝试 10 次后仍未能成功刷新汇率数据。")

#############################################
# 后台刷新数据的工作线程
#############################################
class RefreshWorker(QThread):
    refresh_finished = pyqtSignal(dict, dict)  # 返回 contract_data 与 exchange_rates
    error_occurred = pyqtSignal(str)

    def run(self):
        try:
            contracts = {
                "JO_165751": "沪金2504",
                "JO_165753": "沪金2506",
                "JO_165755": "沪金2508",
                "JO_92233": "伦敦金",
                "JO_12552": "COMEX"
            }
            local_contract_data = {}
            for code in contracts:
                cname, price, update_time = get_contract_data(code)
                if cname is not None:
                    local_contract_data[code] = {
                        "name": cname,
                        "price": price,
                        "update_time": update_time
                    }
                else:
                    print(f"数据获取失败：{contracts[code]}")
            local_exchange_rates = get_exchange_rate_data()
            cnh_rate = get_cnh_rate()
            if cnh_rate is not None:
                local_exchange_rates["离岸人民币汇率"] = cnh_rate
            self.refresh_finished.emit(local_contract_data, local_exchange_rates)
        except Exception as e:
            self.error_occurred.emit(str(e))

#############################################
# 主窗口（基于 PyQt5 的图形界面）
#############################################
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("期货合约价差计算器")
        self.contract_data = {}   # 合约数据
        self.exchange_rates = {}  # 汇率数据
        self.refresh_running = False
        self.selected_exchange_keys = set()
        # 初始汇率模式为自动（可选值："auto"、"day"、"night"）
        self.hkex_mode = "auto"

        # --- 新增：最顶部的汇率模式切换区域 ---
        self.btn_toggle_hkex_mode = QPushButton("切换汇率模式")
        self.btn_toggle_hkex_mode.setMinimumWidth(100)
        self.btn_toggle_hkex_mode.setMinimumHeight(30)
        self.btn_toggle_hkex_mode.clicked.connect(self.toggle_hkex_mode)
        self.label_hkex_mode = QLabel("当前模式：自动")
        self.label_hkex_mode.setAlignment(Qt.AlignCenter)
        # 设置明显的背景和边框，确保区域醒目
        mode_top_layout = QHBoxLayout()
        mode_top_layout.addWidget(self.btn_toggle_hkex_mode)
        mode_top_layout.addWidget(self.label_hkex_mode)
        mode_top_layout.addStretch()
        self.top_mode_box = QGroupBox("【汇率模式切换 - 放置在最顶部】")
        self.top_mode_box.setLayout(mode_top_layout)
        self.top_mode_box.setStyleSheet("QGroupBox { background-color: lightyellow; border: 2px solid gray; }")
        self.top_mode_box.setMinimumHeight(60)

        # --- 沪金合约信息区域 ---
        self.table_sh = QTableWidget()
        self.table_sh.setColumnCount(2)
        self.table_sh.setHorizontalHeaderLabels(["合约名称", "价格"])
        self.group_sh = QGroupBox("沪金合约信息")
        sh_layout = QVBoxLayout()
        sh_layout.addWidget(self.table_sh)
        self.group_sh.setLayout(sh_layout)
        self.group_sh.setFixedHeight(200)

        # --- 汇率列表区域 ---
        self.list_rate = QListWidget()
        self.list_rate.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_rate.itemChanged.connect(self.on_rate_item_changed)
        self.list_rate.setFixedWidth(200)
        self.label_rate = QLabel("选择汇率（可多选）：")
        rate_layout = QVBoxLayout()
        rate_layout.addWidget(self.label_rate)
        rate_layout.addWidget(self.list_rate)
        rate_widget = QWidget()
        rate_widget.setLayout(rate_layout)

        # --- 伦敦金信息区域 ---
        self.label_ld_price = QLabel("伦敦金价格：N/A")
        self.label_comex_price = QLabel("COMEX价格：N/A")
        self.label_ld_spread = QLabel("伦敦金价差：N/A")
        self.group_ld = QGroupBox("伦敦金信息")
        ld_layout = QVBoxLayout()
        ld_layout.addWidget(self.label_ld_price)
        ld_layout.addWidget(self.label_comex_price)
        ld_layout.addWidget(self.label_ld_spread)
        self.group_ld.setLayout(ld_layout)

        # --- 底部：汇率列表与伦敦金信息区域 ---
        bottom_h_layout = QHBoxLayout()
        bottom_h_layout.addWidget(rate_widget)
        bottom_h_layout.addWidget(self.group_ld)
        bottom_h_layout.addStretch()

        # --- 自动刷新与计算按钮区域 ---
        self.btn_refresh = QPushButton("刷新数据")
        self.btn_refresh.clicked.connect(self.start_refresh_worker)
        self.btn_toggle_auto = QPushButton("开始自动刷新")
        self.btn_toggle_auto.clicked.connect(self.toggle_auto_refresh)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(10, 600)
        self.spin_interval.setValue(30)
        self.spin_interval.setSuffix(" 秒")
        self.spin_interval.valueChanged.connect(lambda x: self.auto_timer.setInterval(x * 1000))
        self.btn_calc = QPushButton("计算价差")
        self.btn_calc.clicked.connect(self.calculate_spread)
        auto_refresh_layout = QHBoxLayout()
        auto_refresh_layout.addWidget(self.btn_refresh)
        auto_refresh_layout.addWidget(self.btn_toggle_auto)
        auto_refresh_layout.addWidget(QLabel("自动刷新间隔:"))
        auto_refresh_layout.addWidget(self.spin_interval)
        auto_refresh_layout.addWidget(self.btn_calc)
        auto_refresh_layout.addStretch()

        # --- 最后更新时间显示 ---
        self.label_last_time = QLabel("最后更新时间：N/A")
        self.label_last_time.setAlignment(Qt.AlignRight)

        # --- 整体主布局 ---
        main_layout = QVBoxLayout()
        # 将汇率模式切换区域放在最顶部
        main_layout.addWidget(self.top_mode_box)
        main_layout.addWidget(self.group_sh)
        main_layout.addLayout(bottom_h_layout)
        main_layout.addLayout(auto_refresh_layout)
        main_layout.addWidget(self.label_last_time)
        self.setLayout(main_layout)

        self.resize(1000, 600)
        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(self.spin_interval.value() * 1000)
        self.auto_timer.timeout.connect(self.start_refresh_worker)
        self.timer_running = False

    def start_refresh_worker(self):
        if self.refresh_running:
            return
        self.refresh_running = True
        self.refresh_worker = RefreshWorker()
        self.refresh_worker.refresh_finished.connect(self.on_refresh_finished)
        self.refresh_worker.error_occurred.connect(self.on_refresh_error)
        self.refresh_worker.finished.connect(self.on_refresh_done)
        self.refresh_worker.start()

    def on_refresh_finished(self, contract_data, exchange_rates):
        self.contract_data = contract_data
        self.exchange_rates = exchange_rates
        self.list_rate.blockSignals(True)
        self.list_rate.clear()
        for key, rate in self.exchange_rates.items():
            item = QListWidgetItem(f"{key} : {rate}")
            item.setData(Qt.UserRole, rate)
            if self.selected_exchange_keys:
                if key in self.selected_exchange_keys:
                    item.setCheckState(Qt.Checked)
                else:
                    item.setCheckState(Qt.Unchecked)
            else:
                if key == "离岸人民币汇率":
                    item.setCheckState(Qt.Checked)
                else:
                    item.setCheckState(Qt.Unchecked)
            self.list_rate.addItem(item)
        self.list_rate.blockSignals(False)

        if "JO_92233" in self.contract_data:
            ld_price = self.contract_data["JO_92233"]["price"]
            self.label_ld_price.setText(f"伦敦金价格：{ld_price}")
        else:
            self.label_ld_price.setText("伦敦金价格：N/A")
        if "JO_12552" in self.contract_data:
            comex_price = self.contract_data["JO_12552"]["price"]
            self.label_comex_price.setText(f"COMEX价格：{comex_price}")
        else:
            self.label_comex_price.setText("COMEX价格：N/A")

        sh_codes = ["JO_165751", "JO_165753", "JO_165755"]
        sh_data = []
        for code in sh_codes:
            if code in self.contract_data:
                sh_data.append(self.contract_data[code])
        self.table_sh.setRowCount(len(sh_data))
        self.table_sh.setColumnCount(2)
        self.table_sh.setHorizontalHeaderLabels(["合约名称", "价格"])
        for row, contract in enumerate(sh_data):
            self.table_sh.setItem(row, 0, QTableWidgetItem(contract["name"]))
            self.table_sh.setItem(row, 1, QTableWidgetItem(str(contract["price"])))

        self.calculate_spread_sh()
        self.calculate_spread_ld()
        current_time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.label_last_time.setText(f"最后更新时间：{current_time_str}")

    def on_refresh_error(self, error_message):
        QMessageBox.warning(self, "刷新数据", f"数据刷新失败：{error_message}")

    def on_refresh_done(self):
        self.refresh_running = False

    def on_rate_item_changed(self, item):
        self.selected_exchange_keys = set()
        for i in range(self.list_rate.count()):
            it = self.list_rate.item(i)
            if it.checkState() == Qt.Checked:
                key = it.text().split(" : ")[0]
                self.selected_exchange_keys.add(key)
        self.calculate_spread_sh()

    def calculate_spread_ld(self):
        if "JO_92233" not in self.contract_data or "JO_12552" not in self.contract_data:
            self.label_ld_spread.setText("伦敦金价差：N/A")
            return
        london_price = self.contract_data["JO_92233"]["price"]
        comex_price = self.contract_data["JO_12552"]["price"]
        spread = london_price - comex_price
        self.label_ld_spread.setText(f"伦敦金价差：{spread:.4f}")
        current_time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.label_last_time.setText(f"最后更新时间：{current_time_str}")

    def calculate_spread_sh(self):
        if "JO_12552" not in self.contract_data:
            return
        comex_price = self.contract_data["JO_12552"]["price"]
        selected_rates = {}
        for i in range(self.list_rate.count()):
            item = self.list_rate.item(i)
            if item.checkState() == Qt.Checked:
                key = item.text().split(" : ")[0]
                rate = item.data(Qt.UserRole)
                selected_rates[key] = rate
        base_columns = 2
        extra_columns = len(selected_rates)
        total_columns = base_columns + extra_columns
        headers = ["合约名称", "价格"] + list(selected_rates.keys())
        self.table_sh.setColumnCount(total_columns)
        self.table_sh.setHorizontalHeaderLabels(headers)
        row_count = self.table_sh.rowCount()
        for row in range(row_count):
            price_item = self.table_sh.item(row, 1)
            if price_item is None:
                continue
            try:
                price = float(price_item.text())
            except:
                continue
            col = base_columns
            for rate_name, rate_value in selected_rates.items():
                spread = price - (comex_price * rate_value / 31.103)
                self.table_sh.setItem(row, col, QTableWidgetItem(f"{spread:.4f}"))
                col += 1
        current_time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.label_last_time.setText(f"最后更新时间：{current_time_str}")

    def calculate_spread(self):
        self.calculate_spread_ld()
        self.calculate_spread_sh()

    def toggle_auto_refresh(self):
        if not self.timer_running:
            self.auto_timer.start()
            self.timer_running = True
            self.btn_toggle_auto.setText("停止自动刷新")
            QMessageBox.information(self, "自动刷新", f"自动刷新已启动，每 {self.spin_interval.value()} 秒刷新一次。")
        else:
            self.auto_timer.stop()
            self.timer_running = False
            self.btn_toggle_auto.setText("开始自动刷新")
            QMessageBox.information(self, "自动刷新", "自动刷新已停止。")

    def toggle_hkex_mode(self):
        global manual_session_type
        if self.hkex_mode == "auto":
            self.hkex_mode = "day"
            manual_session_type = 0
        elif self.hkex_mode == "day":
            self.hkex_mode = "night"
            manual_session_type = 1
        else:
            self.hkex_mode = "auto"
            manual_session_type = None
        self.label_hkex_mode.setText(f"当前模式：{'自动' if self.hkex_mode=='auto' else ('白天' if self.hkex_mode=='day' else '夜盘')}")
        self.start_refresh_worker()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
