from database.database import Database
import logging


headers = {
    'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'}
cookies = {
    'ngaPassportUid': '5337595',
    'ngaPassportCid': 'X9r3v6avhskvr9jvadop7jlgm76g3d5ovcj37qjr',
    'lastvisit': 'DONT MODIFY',
    'lastpath': 'DONT MODIFY',
}

ver = '3'
totalfloor = []  # [0]int几层，[1]int pid,  [2]str时间，[3]str昵称，[4]str内容，[5]int赞数, [6]int authorId 
tid = 0
title = 'title'
localmaxpage = 1
localmaxfloor = -1
# (在single里用)部分楼层有评论，content是挂在被评论楼层的，所以先放在这里，之后判断当前楼层是否是评论楼层（是的话没有content），是的话就直接读成这里 int pid，str时间，str昵称，str内容，int赞数
commentreply = []
errortext = ''

def StarCrawl(tid):
    global ver
    if cookies['ngaPassportUid'][0] == '_' or cookies['ngaPassportCid'][0] == '_':
        print('Please edit *cookies* info in the code file first... ref: https://github.com/ludoux/ngapost2md/issues/19#issuecomment-784176804 ')
        input('Press to exit.')
        exit(0)
    tid = 44054712 

def init_db(tid):
    db = Database.Create() 
    # 表名以 tid 命名
    table_name = f"tid_{tid}"
    try:
        create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    lou INTEGER PRIMARY KEY,
                    pid INTEGER,
                    postdate TEXT,
                    username TEXT,
                    content TEXT,
                    score INTEGER,
                    authorid INTEGER
                )
                """
        db.execute(create_table_sql)
    except Exception as e:
        logger.error(f"创建 nga 帖子 tid 错误: {str(e)}")
        raise
    finally:
        db.close()

def get_max_lou(tid):
    try:
        db = Database.Create()
        query = f"SELECT MAX(lou) FROM tid_{tid}"
        results = db.execute(query)
        res = results.fetchone()[0]
        return res if res is not None else -1
           
    except Exception as e:
        logger.error(f"获取股票列表失败: {str(e)}")
        return []
    finally:
        db.close()
