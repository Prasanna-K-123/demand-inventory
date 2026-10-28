"""A setup error must not leak the just-opened SQLite connection."""
from pathlib import Path
import sqlite3
from unittest.mock import Mock
import pytest
from stockout.ledger import Ledger


@pytest.mark.parametrize('failed_statement', [
    'PRAGMA foreign_keys=ON', 'PRAGMA busy_timeout=15000', 'PRAGMA synchronous=FULL',
])
def test_setup_failure_always_closes_connection(monkeypatch, failed_statement):
    connection = Mock(in_transaction=False)
    def execute(statement):
        if statement == failed_statement:
            raise sqlite3.DatabaseError('injected setup failure')
    connection.execute.side_effect = execute
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: connection)
    ledger = Ledger.__new__(Ledger)
    ledger.path = Path('unused.sqlite')
    with pytest.raises(sqlite3.DatabaseError, match='injected setup failure'):
        with ledger.connect():
            pytest.fail('setup failure must prevent the caller using the connection')
    connection.close.assert_called_once()
    connection.rollback.assert_not_called()


def test_body_failure_rolls_back_and_closes(monkeypatch):
    connection = Mock(in_transaction=True)
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: connection)
    ledger = Ledger.__new__(Ledger)
    ledger.path = Path('unused.sqlite')
    with pytest.raises(RuntimeError, match='injected transaction failure'):
        with ledger.connect():
            raise RuntimeError('injected transaction failure')
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    connection.commit.assert_not_called()


def test_single_writer_service_uses_delete_full(tmp_path):
    ledger=Ledger(tmp_path/'ledger.sqlite')
    with ledger.connect() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
        assert connection.execute('PRAGMA synchronous').fetchone()[0]==2
