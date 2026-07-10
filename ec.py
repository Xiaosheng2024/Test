import sys
import pandas as pd
import akshare as ak
import numpy as np
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, 
                            QTableWidget, QTableWidgetItem, QLabel, QHBoxLayout)
from PyQt5.QtCore import QTimer, QDateTime, QTime, Qt
from PyQt5.QtGui import QColor, QFont
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

# ================== 策略计算模块 ==================
def calculate_rsi(data, window=14):
    """计算RSI指标"""
    delta = data['current_price'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(data, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    ema_fast = data['current_price'].ewm(span=fast, adjust=False).mean()
    ema_slow = data['current_price'].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

def calculate_bollinger_bands(data, window=20, num_std=2):
    """扩展1：布林带策略"""
    data['MA20'] = data['current_price'].rolling(window=window).mean()
    data['Upper'] = data['MA20'] + (data['current_price'].rolling(window=window).std() * num_std)
    data['Lower'] = data['MA20'] - (data['current_price'].rolling(window=window).std() * num_std)
    data['BB_Buy'] = data['current_price'] < data['Lower']
    data['BB_Sell'] = data['current_price'] > data['Upper']
    return data

def generate_trading_signals(data):
    """生成综合交易信号"""
    # RSI信号
    data['RSI_超卖'] = (data['RSI'] < 30) & (data['RSI'].shift(1) >= 30)
    data['RSI_超买'] = (data['RSI'] > 70) & (data['RSI'].shift(1) <= 70)
    
    # MACD信号
    data['MACD_金叉'] = (data['MACD'] > data['MACD_signal']) & (data['MACD'].shift(1) <= data['MACD_signal'].shift(1))
    data['MACD_死叉'] = (data['MACD'] < data['MACD_signal']) & (data['MACD'].shift(1) >= data['MACD_signal'].shift(1))
    
    # 布林带信号
    data = calculate_bollinger_bands(data)
    
    # 综合信号（优先级：布林带 > RSI > MACD）
    conditions = [
        data['BB_Buy'] | data['RSI_超卖'] | data['MACD_金叉'],
        data['BB_Sell'] | data['RSI_超买'] | data['MACD_死叉']
    ]
    choices = ['买入', '卖出']
    data['原始信号'] = np.select(conditions, choices, default='持有')
    
    # 扩展3：风险控制
    data = apply_risk_management(data)
    return data

def apply_risk_management(data, stop_loss=0.97, take_profit=1.05):
    """扩展3：风险控制模块"""
    data['持仓'] = 0
    data['止损价'] = np.nan
    entry_price = None
    
    for i in range(1, len(data)):
        # 开仓逻辑
        if data['原始信号'].iloc[i] == '买入' and data['持仓'].iloc[i-1] == 0:
            entry_price = data['current_price'].iloc[i]
            data['持仓'].iloc[i] = 1
            data['止损价'].iloc[i] = entry_price * stop_loss
        # 平仓逻辑
        elif data['持仓'].iloc[i-1] == 1:
            current_price = data['current_price'].iloc[i]
            # 触发止损/止盈
            if current_price <= data['止损价'].iloc[i-1] or current_price >= entry_price * take_profit:
                data['持仓'].iloc[i] = 0
                data['原始信号'].iloc[i] = '强制平仓'
            else:
                data['持仓'].iloc[i] = 1
                data['止损价'].iloc[i] = data['止损价'].iloc[i-1]
    data['最终信号'] = np.where(data['持仓'] == 1, '持有', data['原始信号'])
    return data

def backtest_strategy(data, initial_capital=100000):
    """扩展2：历史回测"""
    data['收益'] = data['current_price'].pct_change()
    data['策略收益'] = data['持仓'].shift(1) * data['收益']
    data['累计收益'] = (1 + data['策略收益']).cumprod() * initial_capital
    data['回撤'] = data['累计收益'] / data['累计收益'].cummax() - 1
    return data

# ================== GUI界面增强 ==================
class FuturesDataApp(QWidget):
    def __init__(self):
        super().__init__()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_data)
        self.figure = plt.figure()  # Initialize the figure first
        self.canvas = FigureCanvas(self.figure)  # Initialize the canvas
        self.initUI()
        self.start_timer()
        
    def initUI(self):
        self.setWindowTitle("智能期货策略系统")
        self.setGeometry(200, 200, 1400, 800)
        main_layout = QHBoxLayout()
        
        # 左侧面板
        left_panel = QVBoxLayout()
        
        # 状态栏
        self.status_label = QLabel("系统就绪")
        self.status_label.setFont(QFont('Arial', 12, QFont.Bold))
        left_panel.addWidget(self.status_label)
        
        # 数据表格
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        left_panel.addWidget(self.table)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新数据")
        self.btn_refresh.clicked.connect(self.load_data)
        self.btn_backtest = QPushButton("执行回测")
        self.btn_backtest.clicked.connect(self.show_backtest)
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_backtest)
        left_panel.addLayout(btn_layout)
        
        # 右侧图表
        right_panel = QVBoxLayout()
        right_panel.addWidget(self.canvas)  # Now that canvas is initialized, it can be added
        
        main_layout.addLayout(left_panel, 60)
        main_layout.addLayout(right_panel, 40)
        self.setLayout(main_layout)
        
        self.load_data()

    def start_timer(self):
        """根据交易时间设置定时器"""
        if self.is_trading_time():
            self.timer.start(30000)
            self.status_label.setText("🟢 交易时段: 实时更新中...")
        else:
            self.timer.start(300000)
            self.status_label.setText("🔴 非交易时段: 低频更新中...")

    def is_trading_time(self):
        """判断国内期货交易时间"""
        current_time = QDateTime.currentDateTime().time()
        return (QTime(9, 0) <= current_time <= QTime(10, 15)) or \
               (QTime(10, 30) <= current_time <= QTime(11, 30)) or \
               (QTime(13, 30) <= current_time <= QTime(15, 0))

    def load_data(self):
        try:
            contracts = ["EC2502", "EC2504", "EC2506", "EC2508", "EC2510", "EC2512"]
            combined_df = pd.DataFrame()
            
            for contract in contracts:
                df = ak.futures_zh_spot(symbol=contract, market="CF", adjust="0")
                if df.empty:
                    continue
                
                # 策略计算
                df['RSI'] = calculate_rsi(df)
                df['MACD'], df['MACD_signal'] = calculate_macd(df)
                df = generate_trading_signals(df)
                df = backtest_strategy(df)
                
                combined_df = pd.concat([combined_df, df], ignore_index=True)
            
            if not combined_df.empty:
                self.current_data = combined_df
                self.display_data(combined_df)
                self.plot_backtest(combined_df)
                self.status_label.setText(f"🔄 最后更新: {QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')}")
            else:
                self.status_label.setText("⚠️ 未获取到有效数据")
                
        except Exception as e:
            self.status_label.setText(f"❌ 错误: {str(e)}")

    def display_data(self, df):
        """优化数据显示"""
        columns = ['symbol', 'time', 'current_price', 'RSI', 'MACD', 
                 '最终信号', '止损价', '累计收益', '回撤']
        df_display = df[columns].copy()
        df_display.columns = ['合约', '时间', '最新价', 'RSI', 'MACD', 
                            '信号', '止损价', '累计收益', '最大回撤']
        
        self.table.setRowCount(df_display.shape[0])
        self.table.setColumnCount(df_display.shape[1])
        self.table.setHorizontalHeaderLabels(df_display.columns)
        
        for row_idx, row in df_display.iterrows():
            for col_idx, val in enumerate(row):
                item = QTableWidgetItem(str(round(val, 2) if isinstance(val, (float, np.number)) else val))
                
                # 信号颜色
                if df_display.columns[col_idx] == '信号':
                    color_map = {
                        '买入': QColor('#4CAF50'), 
                        '卖出': QColor('#FF5252'),
                        '强制平仓': QColor('#FF9800')
                    }
                    item.setBackground(color_map.get(str(val), QColor('#FFFFFF')))
                
                # 收益颜色
                elif df_display.columns[col_idx] in ['累计收益', '最大回撤']:
                    item.setForeground(QColor('#4CAF50') if val > 0 else QColor('#FF5252'))
                
                self.table.setItem(row_idx, col_idx, item)
        
        self.table.resizeColumnsToContents()

    def plot_backtest(self, df):
        """扩展2：绘制回测图表"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        # 绘制累计收益曲线
        ax.plot(df['time'], df['累计收益'], label='策略收益', color='#2196F3')
        ax.fill_between(df['time'], df['累计收益'], alpha=0.1, color='#2196F3')
        
        # 标记交易信号
        buy_signals = df[df['最终信号'] == '买入']
        sell_signals = df[df['最终信号'] == '卖出']
        ax.scatter(buy_signals['time'], buy_signals['累计收益'], 
                  marker='^', color='#4CAF50', s=100, label='买入')
        ax.scatter(sell_signals['time'], sell_signals['累计收益'],
                  marker='v', color='#FF5252', s=100, label='卖出')
        
        ax.set_title('策略回测表现', fontsize=14)
        ax.set_xlabel('时间')
        ax.set_ylabel('累计收益')
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        self.canvas.draw()

    def show_backtest(self):
        """显示详细回测报告"""
        if hasattr(self, 'current_data'):
            df = self.current_data
            max_drawdown = df['回撤'].min() * 100
            total_return = (df['累计收益'].iloc[-1] / 100000 - 1) * 100
            win_rate = len(df[df['策略收益'] > 0]) / len(df[df['策略收益'] != 0]) * 100
            
            report = f"""
            === 回测报告 ===
            累计收益率: {total_return:.2f}%
            最大回撤: {max_drawdown:.2f}%
            胜率: {win_rate:.2f}%
            交易次数: {len(df[df['最终信号'].isin(['买入','卖出'])])}
            """
            self.status_label.setText(report)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = FuturesDataApp()
    ex.show()
    sys.exit(app.exec_())