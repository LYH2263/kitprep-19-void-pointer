import os

# 必须在导入 app.* 之前：app.database 会在模块加载时按 DATABASE_URL 建引擎。
# 测试整体走 SQLite 内存库（见 test_prep_void.db_factory），默认引擎仅为导入期占位。
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SEED_ON_EMPTY", "false")
