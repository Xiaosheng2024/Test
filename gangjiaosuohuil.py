import requests
import json
import time
import random
from datetime import datetime
import pytz

# 浏览器指纹配置（2025年最新Chrome版本）
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
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

# 通过浏览器手动获取最新token（有效期约2小时）
TOKEN_MAP = {
    "day": "evLtsLsBNAUVTPxtGqVeG48hg9MAP9GxfF1kuI/d08jNXxWPutx3Ph6ilmoLDZjw",
    "night": "evLtsLsBNAUVTPxtGqVeG%2B79nim8Z7cABrRqMob3Q7OnnzGsDQpXCY1xiscLnYmQ"
}

def get_hk_time():
    """获取精确到毫秒的香港时间"""
    return datetime.now(pytz.timezone('Asia/Hong_Kong'))

def generate_anti_params():
    """生成反爬虫参数"""
    timestamp = int(time.time() * 1000)
    return {
        'qid': str(timestamp),
        '_': str(timestamp),
        'callback': f'jQuery{random.randint(1e15,1e16)}_{timestamp}'
    }

def get_futures_data():
    # 创建带cookie持久化的会话
    with requests.Session() as s:
        # 第一阶段：获取基础cookie
        s.get('https://www.hkex.com.hk/', headers=headers, timeout=10)
        
        # 第二阶段：获取动态安全cookie
        s.get('https://www1.hkex.com.hk/hkexwidget/apis/seccheck.jsp', headers=headers, timeout=10)

        # 生成请求参数
        current_time = get_hk_time().time()
        params = {
            'lang': 'chi',
            'token': TOKEN_MAP["day"],  # 发现token可通用
            'ats': 'CUS',
            'type': 1 if (current_time.hour >= 7 and current_time.hour < 19) else 0
        }
        params.update(generate_anti_params())

        # 手动构建URL防止二次编码
        base_url = "https://www1.hkex.com.hk/hkexwidget/data/getderivativesfutures"
        query = '&'.join([f"{k}={v}" for k,v in params.items()])
        final_url = f"{base_url}?{query}"
        print("最终请求URL:", final_url)

        # 发送请求
        response = s.get(final_url, headers=headers, timeout=15)
        
        # 调试输出
        print("响应状态码:", response.status_code)
        print("响应头中的Cookie:", response.cookies.get_dict())
        
        # 处理403错误
        if response.status_code == 403:
            raise PermissionError("访问被拒绝，请确认：1.使用香港IP 2.Token有效性 3.系统时间误差")

        # 解析数据
        json_str = response.text.split('(',1)[1].rsplit(')',1)[0]
        data = json.loads(json_str)
        
        # 输出结果
        print(f"\n最后更新时间：{data['data']['lastupd']}")
        for item in data['data']['futureslist']:
            print(f"{item['con_l']} | {item['se']}")

if __name__ == "__main__":
    try:
        get_futures_data()
    except Exception as e:
        print(f"操作失败：{str(e)}")
        print("解决方案：")
        print("1. 使用香港服务器/代理（推荐阿里云香港节点）")
        print("2. 通过浏览器获取最新Token（教程：https://shorturl.at/xyz79）")
        print("3. 检查系统时间与香港时间误差（需控制在1分钟以内）")
