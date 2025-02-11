import sys
import requests
import re
import time
import json
import random
from datetime import datetime
import pytz
from urllib.parse import urlparse, parse_qs, unquote

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QRadioButton, QButtonGroup, QGroupBox, QMessageBox, QSpinBox,
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

#############################################
# 第一部分：数据抓取相关函数
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
    为避免抓取到“失败的” token（即包含 “+” 的 token），
    使用正则提取 URL 中 token 后调用 unquote，并过滤掉包含“+”的 token。
    """
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        # 开启性能日志
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print("Selenium 初始化失败：", str(e))
        return None

    try:
        url = "https://www.hkex.com.hk/products/listed-derivatives/foreign-exchange/usd-cnh-futures?sc_lang=zh-hk#&product=CUS"
        driver.get(url)
        # 等待页面加载和网络请求
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
                        # 如果 token 中包含 "+" 则跳过（你观察到成功 token 不包含 "+"）
                        if '+' in token_candidate:
                            print("跳过包含 '+' 的 token:", token_candidate)
                            continue
                        token = token_candidate
                        break
            except Exception as e:
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
    """
    自动获取最新 token。
    优先使用 Selenium 方法（如果可用），否则返回 None。
    """
    if SELENIUM_AVAILABLE:
        token = fetch_latest_token_selenium()
        return token
    else:
        print("Selenium 不可用，无法自动更新 token")
        return None

def get_exchange_rate_data():
    """
    获取汇率数据：返回字典 { con_l: se }  
    """
    global current_token
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
        if hk_time.weekday() in [5, 6]:
            session_type = 0
        else:
            session_type = 1 if (hk_time.hour >= 7 and hk_time.hour < 19) else 0

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
# 第二部分：后台刷新数据的工作线程
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
            self.refresh_finished.emit(local_contract_data, local_exchange_rates)
        except Exception as e:
            self.error_occurred.emit(str(e))

#############################################
# 第三部分：基于 PyQt5 的图形界面
#############################################

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("期货合约价差计算器")
        self.contract_data = {}   # 合约数据
        self.exchange_rates = {}  # 汇率数据
        self.refresh_running = False

        # -------------------------------
        # 金价来源选择：沪金合约 vs 伦敦金
        # -------------------------------
        self.radio_sh = QRadioButton("沪金合约")
        self.radio_ld = QRadioButton("伦敦金")
        self.radio_sh.setChecked(True)
        self.gold_source_group = QButtonGroup(self)
        self.gold_source_group.addButton(self.radio_sh)
        self.gold_source_group.addButton(self.radio_ld)

        # -------------------------------
        # 伦敦金模式：直接显示伦敦金、COMEX 价格及价差
        # -------------------------------
        self.label_ld_price = QLabel("伦敦金价格：N/A")
        self.label_comex_price = QLabel("COMEX价格：N/A")
        self.label_ld_spread = QLabel("价差：N/A")

        self.group_ld = QGroupBox("伦敦金信息")
        ld_layout = QVBoxLayout()
        ld_layout.addWidget(self.label_ld_price)
        ld_layout.addWidget(self.label_comex_price)
        ld_layout.addWidget(self.label_ld_spread)
        self.group_ld.setLayout(ld_layout)

        # -------------------------------
        # 沪金模式：展示所有沪金合约信息 & 多选汇率
        # -------------------------------
        self.table_sh = QTableWidget()
        self.table_sh.setColumnCount(3)
        self.table_sh.setHorizontalHeaderLabels(["合约名称", "价格", "更新时间"])

        self.list_rate = QListWidget()
        # 设置为不响应列表选择（仅使用复选框）
        self.list_rate.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_rate.itemChanged.connect(self.on_rate_item_changed)

        self.group_sh = QGroupBox("沪金合约信息")
        sh_layout = QVBoxLayout()
        sh_layout.addWidget(self.table_sh)
        sh_layout.addWidget(QLabel("选择汇率（可多选）："))
        sh_layout.addWidget(self.list_rate)
        self.group_sh.setLayout(sh_layout)

        # -------------------------------
        # 底部：最后刷新时间及操作按钮
        # -------------------------------
        self.label_last_time = QLabel("最后计算时间：N/A")
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

        # -------------------------------
        # 主布局
        # -------------------------------
        main_layout = QVBoxLayout()
        source_group = QGroupBox("选择黄金价格来源")
        source_layout = QHBoxLayout()
        source_layout.addWidget(self.radio_sh)
        source_layout.addWidget(self.radio_ld)
        source_group.setLayout(source_layout)
        main_layout.addWidget(source_group)
        main_layout.addWidget(self.group_sh)
        main_layout.addWidget(self.group_ld)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_toggle_auto)
        btn_layout.addWidget(QLabel("自动刷新间隔:"))
        btn_layout.addWidget(self.spin_interval)
        btn_layout.addWidget(self.btn_calc)
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(self.label_last_time)
        self.setLayout(main_layout)

        # 自动刷新定时器
        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(self.spin_interval.value() * 1000)
        self.auto_timer.timeout.connect(self.start_refresh_worker)
        self.timer_running = False

        # 根据选择切换显示
        self.radio_sh.toggled.connect(self.update_ui_mode)
        self.radio_ld.toggled.connect(self.update_ui_mode)
        self.update_ui_mode()

    def update_ui_mode(self):
        """根据金价来源显示不同控件"""
        if self.radio_sh.isChecked():
            self.group_sh.show()
            self.group_ld.hide()
            self.calculate_spread_sh()
        else:
            self.group_ld.show()
            self.group_sh.hide()
            self.calculate_spread_ld()

    def start_refresh_worker(self):
        """启动刷新线程"""
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

        # 更新汇率列表（保留原有选中状态）
        current_checked = set()
        for i in range(self.list_rate.count()):
            item = self.list_rate.item(i)
            if item.checkState() == Qt.Checked:
                # 此处用列表项显示的 key（“con_l”）作为标识
                current_checked.add(item.text().split(" : ")[0])
        self.list_rate.blockSignals(True)
        self.list_rate.clear()
        for key, rate in self.exchange_rates.items():
            item = QListWidgetItem(f"{key} : {rate}")
            item.setData(Qt.UserRole, rate)
            # 如果之前没有选中状态，则默认全部选中
            if not current_checked or key in current_checked:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.list_rate.addItem(item)
        self.list_rate.blockSignals(False)

        # 更新伦敦金信息
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

        # 更新沪金合约表格（仅合同信息，汇率价差在 calculate_spread_sh 中计算）
        sh_codes = ["JO_165751", "JO_165753", "JO_165755"]
        sh_data = []
        for code in sh_codes:
            if code in self.contract_data:
                sh_data.append(self.contract_data[code])
        self.table_sh.setRowCount(len(sh_data))
        for row, contract in enumerate(sh_data):
            self.table_sh.setItem(row, 0, QTableWidgetItem(contract["name"]))
            self.table_sh.setItem(row, 1, QTableWidgetItem(str(contract["price"])))
            self.table_sh.setItem(row, 2, QTableWidgetItem(contract["update_time"]))

        # 根据当前选择模式计算价差
        self.calculate_spread()
        current_time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.label_last_time.setText(f"最后计算时间：{current_time_str}")

    def on_refresh_error(self, error_message):
        QMessageBox.warning(self, "刷新数据", f"数据刷新失败：{error_message}")

    def on_refresh_done(self):
        self.refresh_running = False

    def on_rate_item_changed(self, item):
        # 当汇率选择变化时，若处于沪金模式，则重新计算价差
        if self.radio_sh.isChecked():
            self.calculate_spread_sh()

    def calculate_spread(self):
        if self.radio_sh.isChecked():
            self.calculate_spread_sh()
        else:
            self.calculate_spread_ld()

    def calculate_spread_ld(self):
        # 伦敦金模式：价差 = 伦敦金价格 - COMEX价格
        if "JO_92233" not in self.contract_data or "JO_12552" not in self.contract_data:
            QMessageBox.warning(self, "计算价差", "伦敦金或COMEX数据不可用！")
            return
        london_price = self.contract_data["JO_92233"]["price"]
        comex_price = self.contract_data["JO_12552"]["price"]
        spread = london_price - comex_price
        self.label_ld_spread.setText(f"价差：{spread:.4f}")
        current_time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.label_last_time.setText(f"最后计算时间：{current_time_str}")

    def calculate_spread_sh(self):
        # 沪金模式：对每个合同和每个选中汇率计算价差 = 合约价格 - (COMEX价格 * 汇率 / 31.103)
        if "JO_12552" not in self.contract_data:
            QMessageBox.warning(self, "计算价差", "COMEX数据不可用！")
            return
        comex_price = self.contract_data["JO_12552"]["price"]
        selected_rates = {}
        for i in range(self.list_rate.count()):
            item = self.list_rate.item(i)
            if item.checkState() == Qt.Checked:
                text = item.text()
                key = text.split(" : ")[0]
                rate = item.data(Qt.UserRole)
                selected_rates[key] = rate

        # 更新表格列数：固定 3 列 + 每个选中汇率一列
        num_extra = len(selected_rates)
        total_cols = 3 + num_extra
        self.table_sh.setColumnCount(total_cols)
        headers = ["合约名称", "价格", "更新时间"] + [f"{k}" for k in selected_rates.keys()]
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
            col = 3
            for rate_name, rate_value in selected_rates.items():
                spread = price - (comex_price * rate_value / 31.103)
                self.table_sh.setItem(row, col, QTableWidgetItem(f"{spread:.4f}"))
                col += 1
        current_time_str = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.label_last_time.setText(f"最后计算时间：{current_time_str}")

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

#############################################
# 主程序入口
#############################################

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
