"""
test_watchlist.py
-----------------
watchlist.py のユニットテスト。

ファイルI/Oはすべて tmp_path フィクスチャで隔離し、
実際の watchlists.json に影響を与えない。
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from watchlist import (
    load_watchlists,
    get_watchlist,
    add_watchlist,
    delete_watchlist,
    list_watchlist_names,
)

# ============================================================
# Fixtures
# ============================================================

SAMPLE_CONDITIONS = {
    "sectors"  : ["輸送用機器"],
    "max_count": 150,
    "per_max"  : 15.0,
    "yield_min": 5.0,
    "use_pbr"  : False,
    "pbr_max"  : 1.0,
    "cap_filter": "指定なし",
}


@pytest.fixture(autouse=True)
def isolated_json(tmp_path, monkeypatch):
    """各テストを tmp_path 内の独立したJSONファイルで実行する。"""
    wl_file = tmp_path / "watchlists.json"
    monkeypatch.chdir(tmp_path)
    return wl_file


# ============================================================
# load_watchlists
# ============================================================

class TestLoadWatchlists:

    def test_returns_empty_list_when_file_missing(self):
        result = load_watchlists()
        assert result == []

    def test_returns_saved_entries(self, isolated_json):
        data = {"watchlists": [{"name": "テスト", "conditions": SAMPLE_CONDITIONS, "created_at": "2026-01-01"}]}
        isolated_json.write_text(json.dumps(data), encoding="utf-8")
        result = load_watchlists()
        assert len(result) == 1
        assert result[0]["name"] == "テスト"

    def test_returns_list_type(self):
        assert isinstance(load_watchlists(), list)


# ============================================================
# get_watchlist
# ============================================================

class TestGetWatchlist:

    def test_returns_none_when_not_found(self):
        assert get_watchlist("存在しない") is None

    def test_returns_entry_by_name(self):
        add_watchlist("高配当ウォッチ", SAMPLE_CONDITIONS)
        result = get_watchlist("高配当ウォッチ")
        assert result is not None
        assert result["name"] == "高配当ウォッチ"

    def test_returns_correct_conditions(self):
        add_watchlist("割安ウォッチ", SAMPLE_CONDITIONS)
        result = get_watchlist("割安ウォッチ")
        assert result["conditions"]["per_max"] == 15.0
        assert result["conditions"]["yield_min"] == 5.0


# ============================================================
# add_watchlist
# ============================================================

class TestAddWatchlist:

    def test_adds_new_entry(self):
        add_watchlist("新規ウォッチ", SAMPLE_CONDITIONS)
        assert "新規ウォッチ" in list_watchlist_names()

    def test_overwrites_existing_entry(self):
        add_watchlist("重複テスト", SAMPLE_CONDITIONS)
        new_conditions = {**SAMPLE_CONDITIONS, "per_max": 20.0}
        add_watchlist("重複テスト", new_conditions)
        names = list_watchlist_names()
        assert names.count("重複テスト") == 1
        assert get_watchlist("重複テスト")["conditions"]["per_max"] == 20.0

    def test_persists_to_json(self, isolated_json):
        add_watchlist("永続化テスト", SAMPLE_CONDITIONS)
        raw = json.loads(isolated_json.read_text(encoding="utf-8"))
        names = [wl["name"] for wl in raw["watchlists"]]
        assert "永続化テスト" in names

    def test_created_at_is_today(self):
        from datetime import date
        add_watchlist("日付テスト", SAMPLE_CONDITIONS)
        result = get_watchlist("日付テスト")
        assert result["created_at"] == str(date.today())

    def test_raises_on_empty_name(self):
        with pytest.raises(ValueError):
            add_watchlist("", SAMPLE_CONDITIONS)

    def test_raises_on_whitespace_only_name(self):
        with pytest.raises(ValueError):
            add_watchlist("   ", SAMPLE_CONDITIONS)

    def test_strips_whitespace_from_name(self):
        add_watchlist("  スペース付き  ", SAMPLE_CONDITIONS)
        # strip後の名前で検索できる
        assert get_watchlist("スペース付き") is not None
        # strip前の名前では見つからない（保存時にstripされているため）
        assert get_watchlist("  スペース付き  ") is None

    def test_multiple_entries_preserved(self):
        add_watchlist("ウォッチA", SAMPLE_CONDITIONS)
        add_watchlist("ウォッチB", {**SAMPLE_CONDITIONS, "per_max": 20.0})
        names = list_watchlist_names()
        assert "ウォッチA" in names
        assert "ウォッチB" in names

    def test_conditions_stored_correctly(self):
        add_watchlist("条件テスト", SAMPLE_CONDITIONS)
        result = get_watchlist("条件テスト")
        assert result["conditions"] == SAMPLE_CONDITIONS


# ============================================================
# delete_watchlist
# ============================================================

class TestDeleteWatchlist:

    def test_deletes_existing_entry(self):
        add_watchlist("削除対象", SAMPLE_CONDITIONS)
        result = delete_watchlist("削除対象")
        assert result is True
        assert get_watchlist("削除対象") is None

    def test_returns_false_when_not_found(self):
        result = delete_watchlist("存在しない")
        assert result is False

    def test_does_not_delete_other_entries(self):
        add_watchlist("残すウォッチ", SAMPLE_CONDITIONS)
        add_watchlist("消すウォッチ", SAMPLE_CONDITIONS)
        delete_watchlist("消すウォッチ")
        assert get_watchlist("残すウォッチ") is not None

    def test_persists_deletion_to_json(self, isolated_json):
        add_watchlist("削除永続化テスト", SAMPLE_CONDITIONS)
        delete_watchlist("削除永続化テスト")
        raw = json.loads(isolated_json.read_text(encoding="utf-8"))
        names = [wl["name"] for wl in raw["watchlists"]]
        assert "削除永続化テスト" not in names


# ============================================================
# list_watchlist_names
# ============================================================

class TestListWatchlistNames:

    def test_returns_empty_list_when_no_entries(self):
        assert list_watchlist_names() == []

    def test_returns_all_names(self):
        add_watchlist("名前A", SAMPLE_CONDITIONS)
        add_watchlist("名前B", SAMPLE_CONDITIONS)
        names = list_watchlist_names()
        assert set(names) == {"名前A", "名前B"}

    def test_returns_list_type(self):
        assert isinstance(list_watchlist_names(), list)
