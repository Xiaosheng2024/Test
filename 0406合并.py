import requests
import re
import time 

# 请求 URL
url = "https://api.jijinhao.com/sQuoteCenter/realTime.htm"

# 需要抓取的合约代码
contracts = {
    "JO_165751": "沪金2504",
    "JO_165753": "沪金2506",
    "JO_165755": "沪金2508",
    "JO_92233": "伦敦金",
    "JO_12552": "COMEX"
}

# 请求头
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Referer": "https://quote.cngold.org/"
}

# 遍历每个合约请求数据
for code, name in contracts.items():
    timestamp = int(time.time() * 1000)
    params = {"code": code, "_": timestamp}
    
    # 发送请求
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        match = re.search(r'var hq_str = "(.*?)";', response.text)
        
        if match:
            data = match.group(1)
            fields = data.split(',')

            # 动态获取合约名称（第一项）
            contract_name = fields[0]
            price = fields[3]  # 第四个字段是当前价格
            update_time = f"{fields[-3]} {fields[-2]}"  # 最后两个字段是日期和时间

            print(f"{contract_name}: {price}")
            print(f"更新时间: {update_time}\n")
        else:
            print(f"{name} 未找到数据")
    else:
        print(f"请求 {name} 失败: {response.status_code}")
