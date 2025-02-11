import requests
import re
import time 
url = "https://api.jijinhao.com/realtime/quotejs.htm"

timestamp = int(time.time() * 1000)
params = {
    'codes': 'JO_92233',
    'currentPage': 1,
    'pageSize': 1,
    '_': timestamp
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    'Referer': 'https://www.cngold.org/lundunjin/'
}

response = requests.get(url, headers=headers, params=params)

if response.status_code == 200:
    # 两步精准定位法
    # 第一步：定位到XAU所在区块
    xau_block = re.search(r'"q68":"XAU".*?}', response.text, re.DOTALL)
    
    if xau_block:
        block = xau_block.group()
        # 第二步：在区块内提取q5
        q5_match = re.search(r'"q5":"([0-9.]+)"', block)
        if q5_match:
            print(f"成功提取 XAU 价格: {q5_match.group(1)}")
        else:
            print("找到XAU区块但未发现q5字段")
    else:
        print("响应中未找到XAU数据")
else:
    print(f"请求失败: {response.status_code}")