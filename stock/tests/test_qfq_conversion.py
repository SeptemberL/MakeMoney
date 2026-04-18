import configparser
import os
import tempfile

import pandas as pd

from config import Config
from database.database import Database
from stock_list_manager import StockListManager


def _set_sqlite_config(tmp_db_path: str):
    cfg = Config()
    cp = configparser.ConfigParser()
    cp["DATABASE"] = {"DB_TYPE": "sqlite", "DB_PATH": tmp_db_path}
    cfg._config = cp


def test_db_adj_factor_and_stock_table_qfq_conversion():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        _set_sqlite_config(db_path)

        code = "000001"
        table = StockListManager()._get_stock_table_name(code)
        td = "2026-03-30"

        db = Database.Create()
        try:
            # stock daily raw
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    trade_date DATE PRIMARY KEY,
                    code TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL,
                    volume INTEGER, amount REAL
                )
                """
            )
            db.execute(
                f"INSERT OR REPLACE INTO {table} (trade_date, code, open, high, low, close, volume, amount) VALUES (?,?,?,?,?,?,?,?)",
                (td, code, 10.0, 11.0, 9.0, 10.5, 100, 1000.0),
            )

            # adj_factor
            db.ensure_adj_factor_tables()
            db.upsert_adj_factor(code, td, 2.0)
        finally:
            db.close()

        mgr = StockListManager()
        qfq = mgr.get_stock_data_qfq(code, days=365, missing_adj_factor_policy="skip")
        assert qfq is not None and not qfq.empty
        row = qfq.iloc[-1].to_dict()
        assert pd.to_datetime(row["trade_date"]).strftime("%Y-%m-%d") == td
        assert float(row["open"]) == 20.0
        assert float(row["high"]) == 22.0
        assert float(row["low"]) == 18.0
        assert float(row["close"]) == 21.0


def test_qfq_missing_adj_factor_raw_fallback_keeps_row():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "t.db")
        _set_sqlite_config(db_path)

        code = "000001"
        table = StockListManager()._get_stock_table_name(code)
        td = "2026-03-30"

        db = Database.Create()
        try:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    trade_date DATE PRIMARY KEY,
                    code TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL
                )
                """
            )
            db.execute(
                f"INSERT OR REPLACE INTO {table} (trade_date, code, open, high, low, close) VALUES (?,?,?,?,?,?)",
                (td, code, 10.0, 11.0, 9.0, 10.5),
            )
        finally:
            db.close()

        mgr = StockListManager()
        qfq = mgr.get_stock_data_qfq(code, days=365, missing_adj_factor_policy="raw_fallback")
        assert qfq is not None and not qfq.empty
        row = qfq.iloc[-1].to_dict()
        assert float(row["close"]) == 10.5

