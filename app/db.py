import sqlite3
from pathlib import Path

DB_PATH = Path('data.db')


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS files(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               path TEXT,
               kind TEXT,
               size INTEGER,
               sha256 TEXT,
               source_zip TEXT,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )'''
    )
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS chunks(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               file_id INTEGER,
               idx INTEGER,
               text_path TEXT,
               page_hint INTEGER,
               size INTEGER,
               FOREIGN KEY(file_id) REFERENCES files(id)
           )'''
    )
    cur.execute(
        '''CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(content)'''
    )
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS fts_map(
               rowid INTEGER,
               file_id INTEGER,
               chunk_idx INTEGER,
               page_hint INTEGER
           )'''
    )
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS jobs(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               type TEXT,
               status TEXT,
               started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               finished_at TIMESTAMP,
               logs TEXT
           )'''
    )
    conn.commit()
    return conn
