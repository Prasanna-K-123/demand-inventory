"""Success replies must be backed by intact, complete durable SQLite state."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest

spec=importlib.util.spec_from_file_location('benchmark',Path(__file__).resolve().parents[1]/'scripts/benchmark.py')
benchmark=importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def database(path):
    connection=sqlite3.connect(path)
    try:
        connection.executescript('''
            CREATE TABLE jobs(id INTEGER PRIMARY KEY,state TEXT);
            CREATE TABLE results(id INTEGER REFERENCES jobs(id));
            INSERT INTO jobs VALUES (1,'succeeded');
            INSERT INTO results VALUES (1);
        ''')
        connection.commit()
    finally:
        connection.close()


def test_valid_durable_state_passes(tmp_path):
    path=tmp_path/'ledger.sqlite';database(path)
    receipt=benchmark.verify_closed_database(path,{'jobs':1,'results':1})
    assert receipt['integrity_check']==['ok']
    assert receipt['states']=={'succeeded':1}


def test_missing_result_refuses_success(tmp_path):
    path=tmp_path/'ledger.sqlite';database(path)
    connection=sqlite3.connect(path)
    connection.execute('DELETE FROM results');connection.commit();connection.close()
    with pytest.raises(RuntimeError,match='conservation failed'):
        benchmark.verify_closed_database(path,{'jobs':1,'results':1})


def test_foreign_key_violation_refuses_success(tmp_path):
    path=tmp_path/'ledger.sqlite';database(path)
    connection=sqlite3.connect(path)
    connection.execute('UPDATE results SET id=99');connection.commit();connection.close()
    with pytest.raises(RuntimeError,match='integrity failed'):
        benchmark.verify_closed_database(path,{'jobs':1,'results':1})


def test_truncated_database_refuses_success(tmp_path):
    path=tmp_path/'ledger.sqlite';database(path)
    path.write_bytes(path.read_bytes()[:4096])
    with pytest.raises((sqlite3.DatabaseError,RuntimeError)):
        benchmark.verify_closed_database(path,{'jobs':1,'results':1})
