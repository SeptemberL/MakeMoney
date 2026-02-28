import datetime
import ccxt
import pprint # 用于更美观地打印输出
import pandas as pd


class StockGetter_BTC:
    # 行情数据不需要秘钥
    key = "2cb78b33-0ba9-4bfa-943a-abc64cc63fc3"
    secret = ""
    passphrase = "Xuejianlove1!"
    # 实盘：0，虚拟盘：1
    flag = '0'
    # 使用http和https代理，proxies={'http':'xxxxx','https:':'xxxxx'}，与requests中的proxies参数规则相同
    proxies = {}
    # 转发：需搭建转发服务器，可参考：https://github.com/pyted/okx_resender
    proxy_host = None
    apikey = "2cb78b33-0ba9-4bfa-943a-abc64cc63fc3"
    secretkey = "F3E2B34FCF82461B4F56E42CA1E751D6"
    #IP = ""
    #备注名 = "maintest"
    #权限 = "读取"
    

    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_market()
        return cls._instance
    
    def _init_market(self):
        """初始化数据库连接并检查表是否存在"""
        #self.okx = ccxt.okx()
        self.okx = ccxt.okx({
            'apiKey': self.apikey,
            'secret': self.secretkey,
            
            'password': 'Xuejianlove1!',   
            'timeout': 30000,
            'enableRateLimit': True,
            "proxies":{
                        "http":"http://127.0.0.1:1080",
                        "https":"http://127.0.0.1:1080",
                        }           
        })
        # 实例化market
        #self.market = Market(
        #    key=self.key, secret=self.secret, passphrase=self.passphrase, flag=self.flag, proxies=self.proxies, proxy_host=self.proxy_host,
        #)

    def get_data(self, symbol = "ETH/USDT", timeframe = "1h"):
        print(f"CCXT 版本: {ccxt.__version__}")
        print("支持的交易所:")
        pprint.pprint(ccxt.exchanges)
        print(f"\n总共支持 {len(ccxt.exchanges)} 家交易所")
        exchange = self.okx
        limit = 350 # 获取最近 10 条
        result = None
        # 获取最近 N 条 K 线 (不指定 since)
        try:
            print(f"正在获取 {symbol} 最近 {limit} 条 {timeframe} K 线数据...")
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            if ohlcv:
                # 创建DataFrame并指定列名
                df = pd.DataFrame(
                    ohlcv,
                    columns=['trade_date', 'open', 'high', 'low', 'close', 'volume']
                    #numeric_columns = ['open', 'close', 'high', 'low', 'volume', 'amount', 'p_change', 'turnover_rate']
                )

                # 将毫秒时间戳转换为日期时间索引（关键步骤）
                df['trade_date'] = pd.to_datetime(df['trade_date'], unit='ms')
                #df.set_index('trade_date', inplace=True)
                df['code'] = symbol
                # 按时间升序排序（确保时间序列顺序正确）
                #df.sort_index(inplace=True)
                result = df
                print(df)
            else:
                print("未能获取到 K 线数据")

        except ccxt.NetworkError as e:
            print(f"\n网络错误: {e}")
        except ccxt.ExchangeError as e:
            print(f"\n交易所错误: {e}")
        except Exception as e:
            print(f"\n发生未知错误: {e}")

        return result
        # 注意：load_markets() 只需要调用一次（除非需要刷新），CCXT 会缓存结果
        # 后续调用 exchange.markets 可以直接访问缓存的数据
        # time.sleep(2) # 暂停一下，模拟后续操作
        # print("\n直接访问缓存的市场数据:")
        # cached_markets = exchange.markets
        # print(f"缓存中市场数量: {len(cached_markets)}")


