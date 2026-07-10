import sys
import requests
import threading
import time
from bs4 import BeautifulSoup
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QPushButton, QLineEdit
from PyQt5.QtCore import QTimer

# ==================== API配置 ====================
ALPHA_VANTAGE_KEY = "J9XE0C7KMWH7YDKW"  # 黄金期货数据
EXCHANGE_RATE_KEY = "9be1d1309bdcd99529c2b9af"  # 离岸人民币汇率

# ==================== 全局数据容器 ====================
current_data = {
    "autd_price": 0.0,  # 上海黄金T+D价格（元/克）
    "hlau_price": 0.0,  # 港伦敦金价格（美元/盎司）
    "cnh_rate": 0.0  # 美元兑离岸人民币汇率
}

# ==================== 数据获取模块 ====================
def get_autd_price():
    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/vGold_Matter.php"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'id': 'table'})
        for row in table.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) > 1 and "Au(T+D)" in cells[0].text:
                price = cells[1].text.strip()
                current_data["autd_price"] = float(price)
                return
    except Exception as e:
        print(f"黄金T+D价格获取失败: {str(e)}")

def get_comex_gold_price():
    """从 K780 API 获取 COMEX 黄金价格"""
    url = "https://sapi.k780.com/?app=quote.futures&ftsIdS=31007&appkey=10003&sign=b59bc3ef6191eb9f747dd4e83c99f2a4&format=json"
    try:
        response = requests.get(url)
        data = response.json()
        
        if data.get("success") == "1":
            current_data["hlau_price"] = float(data["conversion_rates"]["CNY"])  # 直接存入 global 数据
        else:
            print(f"获取黄金数据失败: {data.get('msg', '未知错误')}")
    except Exception as e:
        print(f"请求失败: {str(e)}")



def get_cnh_rate():
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_KEY}/latest/USD"
        response = requests.get(url)
        data = response.json()
        print (data)
        current_data["cnh_rate"] = float(data["conversion_rates"]["CNY"])
    
        
    except Exception as e:
        print(f"汇率获取失败: {str(e)}")

# ==================== 计算逻辑 ====================
def calculate_spread():
    return current_data["autd_price"] - (current_data["hlau_price"] * current_data["cnh_rate"] / 31.1035)

# ==================== GUI ====================
class GoldMonitorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.update_thread()

    def initUI(self):
        self.setWindowTitle("黄金价差监控系统")
        layout = QVBoxLayout()
        
        self.label_autd = QLabel("黄金T+D价格: 0.00 元/克")
        self.label_hlau = QLabel("港伦敦金价格: 0.00 美元/盎司")
        self.label_rate = QLabel("离岸汇率: 0.0000")
        self.label_spread = QLabel("实时价差: 0.00")
        
        self.threshold_input = QLineEdit(self)
        self.threshold_input.setPlaceholderText("输入预警阈值")
        self.alert_button = QPushButton("设置提醒阈值", self)
        self.alert_button.clicked.connect(self.check_alert)
        
        layout.addWidget(self.label_autd)
        layout.addWidget(self.label_hlau)
        layout.addWidget(self.label_rate)
        layout.addWidget(self.label_spread)
        layout.addWidget(self.threshold_input)
        layout.addWidget(self.alert_button)
        
        self.setLayout(layout)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_labels)
        self.timer.start(1000)
    
    def update_labels(self):
        self.label_autd.setText(f"到底什么黄金: {current_data['autd_price']:.2f} 元/克")
        self.label_hlau.setText(f"港伦敦金价格: {current_data['hlau_price']:.2f} 美元/盎司")
        self.label_rate.setText(f"离岸汇率: {current_data['cnh_rate']:.4f}")
        self.label_spread.setText(f"实时价差: {calculate_spread():.2f}")
    
    def check_alert(self):
        try:
            threshold = float(self.threshold_input.text())
            spread = calculate_spread()
            if abs(spread) > threshold:
                self.alert_button.setText(f"⚠️ 预警: {spread:.2f} 元/克")
            else:
                self.alert_button.setText("设置提醒阈值")
        except ValueError:
            self.alert_button.setText("请输入有效数字")

    def update_thread(self):
        threading.Thread(target=self.data_update_loop, daemon=True).start()

    def data_update_loop(self):
        """数据更新循环"""
        while True:
            get_autd_price()
            get_comex_gold_price()
            get_cnh_rate()
            time.sleep(30)



# ==================== 运行应用 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = GoldMonitorApp()
    ex.show()
    sys.exit(app.exec_())
