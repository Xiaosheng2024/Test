import requests
import re
import time 
# 请求 URL
url = "https://api.jijinhao.com/sQuoteCenter/realTime.htm"
timestamp = int(time.time() * 1000)
params = {
    "code": "JO_12552",
    "_": timestamp
}

# 请求头
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Referer": "https://quote.cngold.org/"
}

# 发送请求
response = requests.get(url, headers=headers, params=params)

if response.status_code == 200:
    # 提取 hq_str 变量内容
    match = re.search(r'var hq_str = "(.*?)";', response.text)
    
    if match:
        data = match.group(1)
        fields = data.split(',')

        # 提取价格和时间
        price = fields[3]  # 2886.4
        timestamp = f"{fields[-3]} {fields[-2]}"  # 2025-02-08 03:09:12

        print(f"COMEX黄金价格: {price}")
        print(f"更新时间: {timestamp}")
    else:
        print("未找到数据")
else:
    print(f"请求失败: {response.status_code}")
