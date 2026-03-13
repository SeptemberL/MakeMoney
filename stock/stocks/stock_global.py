class StockGlobal:
    _instance = None

    socketio = None #SocketIO(app, cors_allowed_origins="*")
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StockGlobal, cls).__new__(cls)
            cls._instance._init_vars()
        return cls._instance

    def _init_vars(self):
        # 初始化所有全局变量
        self.wx = None
        # 可以继续添加其他全局变量
        # self.some_other_var = None

# 单例对象，项目中直接 import instance 使用
stockGlobal = StockGlobal() 

