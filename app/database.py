import aiosqlite
from config import DATABASE_PATH

DB_PATH = DATABASE_PATH


async def get_db():
    """获取数据库连接（async context manager）"""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """初始化数据库表"""
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                verified INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS verification_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                name TEXT DEFAULT 'default',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (email) REFERENCES users(email)
            );

            CREATE TABLE IF NOT EXISTS sites (
                shortcode TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                title TEXT DEFAULT '',
                size_bytes INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (email) REFERENCES users(email)
            );

            CREATE INDEX IF NOT EXISTS idx_sites_email ON sites(email);
            CREATE INDEX IF NOT EXISTS idx_api_keys_email ON api_keys(email);
            CREATE INDEX IF NOT EXISTS idx_verification_email ON verification_tokens(email);
        """)
        await db.commit()
    finally:
        await db.close()
