"""
watchlist.py
------------
ウォッチリストの保存・読み込みロジック。

データ構造（watchlists.json）:
{
  "watchlists": [
    {
      "name": "任意の名前",
      "conditions": {
        "sectors"     : ["輸送用機器"],   // 空リスト = 全業種
        "max_count"   : 150,
        "per_max"     : 15.0,
        "yield_min"   : 5.0,
        "use_pbr"     : false,
        "pbr_max"     : 1.0,
        "cap_filter"  : "指定なし"
      },
      "created_at": "YYYY-MM-DD"
    }
  ]
}
"""

import json
import os
from datetime import date
from typing import Optional

WATCHLIST_FILE = "watchlists.json"

# ============================================================
# 内部ヘルパー
# ============================================================

def _load_raw() -> dict:
    if not os.path.exists(WATCHLIST_FILE):
        return {"watchlists": []}
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: dict) -> None:
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 公開API
# ============================================================

def load_watchlists() -> list[dict]:
    """保存済みウォッチリストを全件返す。"""
    return _load_raw().get("watchlists", [])


def get_watchlist(name: str) -> Optional[dict]:
    """名前でウォッチリストを1件取得。存在しなければ None。"""
    for wl in load_watchlists():
        if wl["name"] == name:
            return wl
    return None


def add_watchlist(name: str, conditions: dict) -> None:
    """
    ウォッチリストを追加する。同名が存在する場合は上書き。

    Parameters
    ----------
    name       : 任意の表示名
    conditions : スクリーニング条件の辞書（app.py のフィルター設定と対応）
    """
    if not name or not name.strip():
        raise ValueError("ウォッチリスト名が空です")

    data = _load_raw()
    entry = {
        "name"      : name.strip(),
        "conditions": conditions,
        "created_at": str(date.today()),
    }

    existing = [wl for wl in data["watchlists"] if wl["name"] != name.strip()]
    existing.append(entry)
    data["watchlists"] = existing
    _save_raw(data)


def delete_watchlist(name: str) -> bool:
    """
    名前でウォッチリストを削除する。

    Returns
    -------
    bool : 削除できた場合 True、対象が存在しなかった場合 False
    """
    data = _load_raw()
    before = len(data["watchlists"])
    data["watchlists"] = [wl for wl in data["watchlists"] if wl["name"] != name]
    _save_raw(data)
    return len(data["watchlists"]) < before


def list_watchlist_names() -> list[str]:
    """保存済みウォッチリスト名の一覧を返す。"""
    return [wl["name"] for wl in load_watchlists()]
