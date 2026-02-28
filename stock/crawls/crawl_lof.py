import requests
from bs4 import BeautifulSoup
import re
from selenium import webdriver
import selenium
import time


def fetch_fund_data(url):
    """
    从搜狐基金页面抓取基金的单位净值和现价
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:

        print("启动 chrome")
        driver = webdriver.Chrome()
        driver.get(url)
        print("打开 url")
        time.sleep(3)


        # 1. 发送请求获取页面
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 检查请求是否成功
        response.encoding = 'gb2312'
        
        # 2. 解析HTML内容
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        #soup = BeautifulSoup(response, 'lxml', from_encoding='gb2312')

        nav_value = float(find_nav_value(soup))
        
        current_value = float(find_current_price(soup))
        
        fund_name = soup.select_one('li.name a').text.strip()
        fund_code = soup.select_one('li.code').text.strip()

        Premium_Rate = (current_value - nav_value) / nav_value * 100
        Premium_Rate = f"{Premium_Rate:.2f}"
        driver.quit()
        return {
            'fund_name': fund_name,
            'fund_code': fund_code,
            'premium_rate': float(Premium_Rate),
            'unit_nav': nav_value,
            'current_price': current_value
        }
        
    except requests.RequestException as e:
        print(f"网络请求错误: {e}")
        return None
    except Exception as e:
        print(f"解析错误: {e}")
        return None

#Net Asset Value per unit
#单位净值
def find_nav_value(soup):
    # 3. 提取单位净值 - 方法1: 通过包含特定文字的div查找
    nav_value = None
    # 查找包含"单位净值"文字的div
    nav_div = soup.find('div', string=re.compile(r'单位净值\s*\(\d{4}-\d{2}-\d{2}\)'))
        
    if nav_div:
        # 获取下一个兄弟节点中的数值
        next_sibling = nav_div.find_next_sibling('div')
        if next_sibling:
            # 使用正则表达式提取数字
            match = re.search(r'(\d+\.?\d*)', next_sibling.get_text())
            if match:
                nav_value = match.group(1)
       
    # 备用方案: 直接搜索包含"1.9469"这样的数值
    if not nav_value:
        # 在页面中寻找典型的净值格式数字
        all_text = soup.get_text()
        # 寻找类似"1.9469 (0.99%)"的模式
        match = re.search(r'(\d+\.\d{4})\s*\([+-]?\d+\.?\d*%\)', all_text)
        if match:
            nav_value = match.group(1)
    return nav_value

def find_current_price(soup):
    target_div = soup.find('div', class_='row02')

    current_price = 0
    if target_div:
        current_price = target_div.find('span').text.strip()            
        print(f"现价: {current_price}")
    return current_price
    
