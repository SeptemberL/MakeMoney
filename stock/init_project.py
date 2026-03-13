import os
from database.database import Database
import logging
from pathlib import Path

def init_project():
    """初始化项目结构和数据库"""
    # 获取项目根目录
    BASE_DIR = Path(__file__).parent

    # 创建项目目录结构
    directories = [
        'database',
        'logs',
        'static/js',
        'static/css',
        'templates'
    ]
    
    # 创建目录
    for directory in directories:
        dir_path = BASE_DIR / directory
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"创建目录: {dir_path}")

    # 创建日志文件
    log_file = BASE_DIR / 'logs' / 'app.log'
    log_file.touch(exist_ok=True)
    print(f"创建日志文件: {log_file}")
    
    db = Database.Create()
    db.init_database()
    db.commit()
    db.close()
    
    print("项目初始化完成！")
    return BASE_DIR

def setup_logging(base_dir: Path):
    """设置日志配置"""
    log_file = base_dir / 'logs' / 'app.log'
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger(__name__)

if __name__ == "__main__":
    base_dir = init_project()
    logger = setup_logging(base_dir)
    logger.info("项目初始化完成") 