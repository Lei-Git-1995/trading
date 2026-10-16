# -*- coding: utf-8 -*-
"""A股涨停情绪：东财涨停池/炸板池 → 连板高度、晋级、炸板、情绪周期。

移植自 Wealth-Researcher 的 screener.data_limit_up，去掉对 screener 包的依赖，
磁盘缓存改写到本项目 CACHE_DIR。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from stock_selector.config import CACHE_DIR


_CACHE: dict[str, Any] = {"ts": 0.0, "data": None, "refreshing": False}
_CACHE_TTL_SEC = 30.0
_CACHE_TTL_IDLE_SEC = 120.0
_LOCK = threading.Lock()
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
)
_UT = "7eea3edcaed734bea9cbfc24409ed989"


def _is_session_now() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= hm <= (15 * 60)


def _cache_ttl() -> float:
    try:
        return _CACHE_TTL_SEC if _is_session_now() else _CACHE_TTL_IDLE_SEC
    except Exception:
        return _CACHE_TTL_SEC


def _disk_path() -> Path:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / "limit_up_emotion.json"
    except Exception:
        return Path("limit_up_emotion.json")


def _trade_day_candidates(n: int = 6) -> list[str]:
    out = []
    d = datetime.now()
    for _ in range(n * 2):
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
            if len(out) >= n:
                break
        d -= timedelta(days=1)
    return out


def _fetch_pool(kind: str, day: str, *, pagesize: int = 200) -> tuple[list[dict], int]:
    """kind: zt=涨停池 zb=炸板池；返回 (pool_rows, total_count)。"""
    path = "getTopicZTPool" if kind == "zt" else "getTopicZBPool"
    url = f"https://push2ex.eastmoney.com/{path}"
    params = {
        "ut": _UT,
        "dpt": "wz.ztzt",
        "Pageindex": 0,
        "pagesize": pagesize,
        "sort": "fbt:asc",
        "date": day,
    }
    r = _SESSION.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = (r.json() or {}).get("data") or {}
    if not isinstance(data, dict):
        return [], 0
    pool = data.get("pool") or []
    if not isinstance(pool, list):
        pool = []
    tc = int(data.get("tc") or len(pool) or 0)
    return pool, tc


def _norm_zt_row(x: dict) -> dict:
    code = str(x.get("c") or "").zfill(6)
    zttj = x.get("zttj") if isinstance(x.get("zttj"), dict) else {}
    lbc = int(x.get("lbc") or zttj.get("days") or 0)
    return {
        "code": code,
        "name": str(x.get("n") or ""),
        "pct_chg": round(float(x.get("zdp") or 0), 2),
        "board_n": lbc,
        "broken_n": int(x.get("zbc") or 0),
        "first_seal": x.get("fbt"),
        "last_seal": x.get("lbt"),
        "amount": x.get("amount"),
        "industry": str(x.get("hybk") or ""),
        "fund": x.get("fund"),
    }


def _norm_zb_row(x: dict) -> dict:
    code = str(x.get("c") or "").zfill(6)
    return {
        "code": code,
        "name": str(x.get("n") or ""),
        "pct_chg": round(float(x.get("zdp") or 0), 2),
        "broken_n": int(x.get("zbc") or 0),
        "first_seal": x.get("fbt"),
        "industry": str(x.get("hybk") or ""),
    }


def _emotion_phase(
    *,
    limit_up_n: int,
    max_height: int,
    promotion_rate: float | None,
    broken_n: int,
) -> tuple[str, str]:
    promo = float(promotion_rate) if promotion_rate is not None else 0.0
    broken_ratio = (broken_n / limit_up_n) if limit_up_n > 0 else 1.0

    if limit_up_n <= 20 and max_height <= 2:
        return "ice", "冰点"
    if broken_ratio >= 0.55 and max_height >= 4:
        return "fade", "退潮"
    if limit_up_n >= 70 and max_height >= 5 and promo >= 0.25:
        return "climax", "高潮"
    if limit_up_n >= 40 and max_height >= 3 and promo >= 0.18:
        return "climax", "偏高潮"
    if limit_up_n >= 30 and max_height >= 2 and broken_ratio < 0.45:
        return "repair", "修复"
    if limit_up_n < 30 or promo < 0.12:
        return "ice", "偏弱"
    return "repair", "修复震荡"


def _weekday_sessionish(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return (8 * 60) <= hm <= (15 * 60 + 30)


def _load_yest_boards(days: list[str], after_day: str) -> tuple[int, dict[str, int]]:
    yest_n = 0
    yest_boards: dict[str, int] = {}
    if after_day not in days:
        return 0, {}
    idx = days.index(after_day)
    for d in days[idx + 1:]:
        try:
            ypool, ytc = _fetch_pool("zt", d)
        except Exception:
            continue
        if not ypool and not ytc:
            continue
        yest_n = int(ytc or len(ypool) or 0)
        for x in ypool or []:
            c = str(x.get("c") or "").zfill(6)
            if not c or c == "000000":
                continue
            zttj = x.get("zttj") if isinstance(x.get("zttj"), dict) else {}
            try:
                lbc = int(x.get("lbc") or zttj.get("days") or 1)
            except (TypeError, ValueError):
                lbc = 1
            yest_boards[c] = max(lbc, yest_boards.get(c, 0))
        break
    return yest_n, yest_boards


def _build_emotion_out(
    *,
    day_used: str,
    zt_rows: list[dict],
    zb_rows: list[dict],
    yest_n: int,
    yest_boards: dict[str, int],
    err: str,
    today_empty: bool = False,
) -> dict[str, Any]:
    limit_up_n = max(len(zt_rows), 0)
    heights = [int(r.get("board_n") or 0) for r in zt_rows]
    max_height = max(heights) if heights else 0
    promo_n = sum(1 for h in heights if h >= 2)
    promotion_rate = round(promo_n / yest_n, 4) if yest_n > 0 else (
        round(promo_n / limit_up_n, 4) if limit_up_n else None
    )
    broken_n = len(zb_rows)
    if today_empty and limit_up_n <= 0:
        phase, phase_label = "ice", "今日暂无涨停"
    else:
        phase, phase_label = _emotion_phase(
            limit_up_n=limit_up_n,
            max_height=max_height,
            promotion_rate=promotion_rate,
            broken_n=broken_n,
        )
    height_hist: dict[str, int] = {}
    for h in heights:
        key = str(h if h > 0 else 1)
        height_hist[key] = height_hist.get(key, 0) + 1

    leaders = sorted(
        zt_rows, key=lambda x: (-int(x.get("board_n") or 0), -float(x.get("pct_chg") or 0))
    )[:8]
    resealed_n = sum(1 for r in zt_rows if int(r.get("broken_n") or 0) >= 1)
    zt_codes = {str(r.get("code") or "").zfill(6) for r in zt_rows}
    broken_open_n = sum(
        1 for r in zb_rows if str(r.get("code") or "").zfill(6) not in zt_codes
    )
    return {
        "ok": True if today_empty else (limit_up_n > 0 or not err),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "day": day_used,
        "limit_up_n": limit_up_n,
        "broken_seal_n": broken_n,
        "resealed_n": resealed_n,
        "broken_open_n": broken_open_n,
        "max_board_height": max_height,
        "promo_n": promo_n,
        "yest_limit_up_n": yest_n,
        "promotion_rate": promotion_rate,
        "phase": phase,
        "phase_label": phase_label,
        "height_hist": height_hist,
        "leaders": leaders,
        "zt_items": list(zt_rows),
        "broken_samples": zb_rows[:8],
        "broken_all": list(zb_rows),
        "yest_boards": yest_boards,
        "error": err,
        "stale": False,
        "today_empty": bool(today_empty),
        "buy_bias": _buy_bias(phase, max_height, promotion_rate, broken_n, limit_up_n),
    }


def fetch_limit_up_emotion(*, force: bool = False) -> dict[str, Any]:
    now = time.time()
    ttl = _cache_ttl()
    if (
        not force
        and isinstance(_CACHE.get("data"), dict)
        and now - float(_CACHE.get("ts") or 0) < ttl
    ):
        return dict(_CACHE["data"])

    err = ""
    day_used = ""
    zt_rows: list[dict] = []
    zb_rows: list[dict] = []
    yest_n = 0
    yest_boards: dict[str, int] = {}
    today_empty = False
    today = datetime.now().strftime("%Y%m%d")
    days = _trade_day_candidates(8)

    try:
        if datetime.now().weekday() < 5:
            try:
                pool, tc = _fetch_pool("zt", today)
            except Exception as e:
                pool, tc = [], 0
                err = str(e)
            if pool or tc > 0:
                day_used = today
                zt_rows = [_norm_zt_row(x) for x in pool if str(x.get("c") or "").strip()]
            elif _weekday_sessionish():
                today_empty = True
                day_used = today
            elif not pool and not tc:
                for d in days:
                    if d == today:
                        continue
                    try:
                        pool2, tc2 = _fetch_pool("zt", d)
                    except Exception:
                        continue
                    if pool2 or tc2 > 0:
                        day_used = d
                        zt_rows = [_norm_zt_row(x) for x in pool2 if str(x.get("c") or "").strip()]
                        break
        else:
            for d in days:
                try:
                    pool, tc = _fetch_pool("zt", d)
                except Exception as e:
                    err = str(e)
                    continue
                if pool or tc > 0:
                    day_used = d
                    zt_rows = [_norm_zt_row(x) for x in pool if str(x.get("c") or "").strip()]
                    break

        if day_used:
            try:
                zb_pool, _ = _fetch_pool("zb", day_used)
                zb_rows = [_norm_zb_row(x) for x in zb_pool if str(x.get("c") or "").strip()]
            except Exception as e:
                err = (err + "; " if err else "") + f"炸板池: {e}"
            yest_n, yest_boards = _load_yest_boards(days, day_used)
    except Exception as e:
        err = str(e)
        yest_boards = {}

    out = _build_emotion_out(
        day_used=day_used or today,
        zt_rows=zt_rows,
        zb_rows=zb_rows,
        yest_n=yest_n,
        yest_boards=yest_boards,
        err=err,
        today_empty=today_empty,
    )
    if day_used and day_used != today and datetime.now().weekday() < 5:
        out["stale"] = True
        out["error"] = (out.get("error") or "") or f"沿用交易日{day_used}"

    if today_empty:
        short = min(45.0, float(ttl) if ttl else 45.0)
        with _LOCK:
            _CACHE["ts"] = now - float(ttl) + short
            _CACHE["data"] = out
        return dict(out)

    if out.get("ok") and int(out.get("limit_up_n") or 0) > 0:
        with _LOCK:
            _CACHE["ts"] = now
            _CACHE["data"] = out
        try:
            _disk_path().write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return dict(out)

    fb = _CACHE.get("data")
    if not isinstance(fb, dict) or not fb.get("limit_up_n"):
        try:
            fb = json.loads(_disk_path().read_text(encoding="utf-8"))
        except Exception:
            fb = None
    if isinstance(fb, dict) and (fb.get("limit_up_n") or fb.get("ok")):
        fb = dict(fb)
        fb["stale"] = True
        fb["error"] = err or "沿用上次涨停情绪"
        with _LOCK:
            _CACHE["data"] = fb
        return fb

    with _LOCK:
        _CACHE["data"] = out
    return dict(out)


def _buy_bias(
    phase: str,
    max_height: int,
    promotion_rate: float | None,
    broken_n: int,
    limit_up_n: int,
) -> dict[str, Any]:
    promo = float(promotion_rate) if promotion_rate is not None else 0.0
    if phase in ("ice",) or limit_up_n <= 15:
        return {
            "prefer_buy": True,
            "tighten": True,
            "pause_hint": False,
            "trial_ok": True,
            "score_add": 0.0,
            "live_pct_add": 0.0,
            "note": "冰点偏进攻试错：优先攻击带内启动/首板/弱转强，半仓到八成仓；禁贴板死封与高位接力",
        }
    if phase == "fade" or (broken_n >= max(20, limit_up_n * 0.5) and max_height >= 4):
        return {
            "prefer_buy": True,
            "tighten": False,
            "pause_hint": False,
            "trial_ok": True,
            "score_add": -1.0,
            "live_pct_add": 0.0,
            "note": "退潮偏进攻试错：攻击带内可开，优先首板/弱转强；禁高位接力与贴板死封",
        }
    if phase == "climax" and promo >= 0.2:
        return {
            "prefer_buy": True,
            "tighten": False,
            "pause_hint": False,
            "score_add": -3.0,
            "live_pct_add": 0.0,
            "note": "情绪高潮，积极打确认板/回封弱转强",
        }
    return {
        "prefer_buy": True,
        "tighten": False,
        "pause_hint": False,
        "trial_ok": True,
        "score_add": -1.0,
        "live_pct_add": 0.0,
        "note": "修复期偏进攻：低位启动/首二板积极试错",
    }


def get_limit_up_emotion(*, force: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _CACHE.get("data")
    age = now - float(_CACHE.get("ts") or 0)
    ttl = _cache_ttl()
    if not isinstance(cached, dict) or (
        not cached.get("limit_up_n") and not cached.get("today_empty")
    ):
        try:
            disk = json.loads(_disk_path().read_text(encoding="utf-8"))
            if isinstance(disk, dict):
                with _LOCK:
                    if _CACHE.get("data") is None:
                        _CACHE["data"] = disk
                        _CACHE["ts"] = now - ttl
                cached = _CACHE.get("data")
        except Exception:
            pass
    need = force or cached is None or age >= ttl or (
        not (cached or {}).get("limit_up_n") and not (cached or {}).get("today_empty")
    )
    if need:
        ensure_limit_up_refresh_async(force=bool(force or cached is None))
    if isinstance(cached, dict) and (
        cached.get("ok") or cached.get("limit_up_n") or cached.get("today_empty")
    ):
        out = dict(cached)
        if age >= ttl:
            out["stale"] = True
        return out
    return fetch_limit_up_emotion(force=True)


def ensure_limit_up_refresh_async(*, force: bool = False) -> bool:
    with _LOCK:
        if _CACHE.get("refreshing"):
            return False
        _CACHE["refreshing"] = True

    def worker():
        try:
            fetch_limit_up_emotion(force=True)
        except Exception:
            pass
        finally:
            with _LOCK:
                _CACHE["refreshing"] = False

    threading.Thread(target=worker, name="LimitUpEmotionRefresh", daemon=True).start()
    return True


def emotion_brief(emo: dict | None = None) -> dict[str, Any]:
    e = emo or get_limit_up_emotion()
    return {
        "day": e.get("day"),
        "limit_up_n": e.get("limit_up_n"),
        "broken_seal_n": e.get("broken_seal_n"),
        "resealed_n": e.get("resealed_n"),
        "broken_open_n": e.get("broken_open_n"),
        "max_board_height": e.get("max_board_height"),
        "promotion_rate": e.get("promotion_rate"),
        "phase": e.get("phase"),
        "phase_label": e.get("phase_label"),
        "buy_bias": e.get("buy_bias"),
        "leaders": [
            {
                "code": x.get("code"),
                "name": x.get("name"),
                "board_n": x.get("board_n"),
                "broken_n": x.get("broken_n"),
            }
            for x in (e.get("leaders") or [])[:5]
        ],
        "yest_boards_n": len(e.get("yest_boards") or {}),
        "stale": bool(e.get("stale")),
    }
