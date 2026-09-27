# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

# Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []           # Global logs
        self.account_logs: Dict[str, List[Dict]] = {}  # 🔥 Per-account logs
        self.account_history: Dict[str, List[Dict]] = {}  # 🔥 Per-account match history
        self.max_logs = 300
        self.max_account_logs = 100
        self.max_history = 100
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.stop_flags: Dict[str, bool] = {}

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid
        }
        # Global log
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

        # 🔥 Per-account log (only if uid provided)
        if uid:
            uid_str = str(uid)
            if uid_str not in self.account_logs:
                self.account_logs[uid_str] = []
            self.account_logs[uid_str].append(entry)
            if len(self.account_logs[uid_str]) > self.max_account_logs:
                self.account_logs[uid_str].pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": level or 1,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "status": "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
                "is_stopped": False,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            # Init history
            if uid_str not in self.account_history:
                self.account_history[uid_str] = []
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                msg = f"Gained +{diff} EXP! Total Gained: +{acc['gained_exp']}"
                self.log(f"[{acc['nickname']}] {msg}", "success", uid_str)
            self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            acc["matches_played"] += 1
            acc["last_match_time"] = time.strftime("%H:%M:%S")
            acc["last_updated"] = time.strftime("%H:%M:%S")

            # 🔥 Add to per-account history
            history_entry = {
                "match_num": acc["matches_played"],
                "time": time.strftime("%H:%M:%S"),
                "date": time.strftime("%Y-%m-%d"),
                "exp_at_match": acc["current_exp"],
                "gained_exp": acc["gained_exp"],
                "level": acc["level"],
            }
            if uid_str not in self.account_history:
                self.account_history[uid_str] = []
            self.account_history[uid_str].append(history_entry)
            if len(self.account_history[uid_str]) > self.max_history:
                self.account_history[uid_str].pop(0)

            self.log(f"Match #{acc['matches_played']} completed successfully", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())

    # ---- Stop/Resume helpers ----
    def set_stop(self, uid: str):
        self.stop_flags[str(uid)] = True
        if str(uid) in self.accounts:
            self.accounts[str(uid)]["is_stopped"] = True
            self.accounts[str(uid)]["status"] = "STOPPED"
            self.accounts[str(uid)]["active_matches"] = 0

    def resume(self, uid: str):
        self.stop_flags[str(uid)] = False
        if str(uid) in self.accounts:
            self.accounts[str(uid)]["is_stopped"] = False

    def should_stop(self, uid: str) -> bool:
        return self.stop_flags.get(str(uid), False)


bot_state = BotState()


# ==================== HTTP HANDLERS ====================
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")

async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    """Main stats — logs are NOT included to avoid lag."""
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "uptime": int(time.time() - bot_state.start_time)
    })


async def handle_get_account_detail(request: web.Request) -> web.Response:
    """🔥 Per-account detail: history + logs (only loaded when user opens it)."""
    try:
        uid = str(request.query.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "uid required"})

        acc = bot_state.accounts.get(uid, {})
        history = bot_state.account_history.get(uid, [])
        logs = bot_state.account_logs.get(uid, [])

        return web.json_response({
            "status": "ok",
            "account": acc,
            "history": history[-50:],   # last 50 matches
            "logs": logs[-80:],          # last 80 logs
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_get_global_logs(request: web.Request) -> web.Response:
    """🔥 Global logs endpoint — only called when user opens the log panel."""
    return web.json_response({
        "status": "ok",
        "logs": bot_state.logs[-80:]
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd})
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token})
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"New account added: {data.get('uid') or 'Token'}", "success")

        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        accounts_file = "accounts.json"

        if os.path.exists(accounts_file):
            with open(accounts_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            new_list = []
            for acc in existing:
                if str(acc.get("uid")) == uid:
                    continue
                if "token" in acc and str(acc.get("token", ""))[:10] == uid:
                    continue
                new_list.append(acc)
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(new_list, f, indent=2)

        if "on_delete_account" in bot_state.refresh_callbacks:
            await bot_state.refresh_callbacks["on_delete_account"](uid)

        if uid in bot_state.accounts:
            del bot_state.accounts[uid]
        if uid in bot_state.account_logs:
            del bot_state.account_logs[uid]
        if uid in bot_state.account_history:
            del bot_state.account_history[uid]
        if uid in bot_state.account_workers:
            task = bot_state.account_workers.pop(uid, None)
            if task and not task.done():
                task.cancel()

        bot_state.log(f"Account {uid} PERMANENTLY deleted.", "error", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_stop_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        bot_state.set_stop(uid)
        if "on_stop_account" in bot_state.refresh_callbacks:
            await bot_state.refresh_callbacks["on_stop_account"](uid)
        bot_state.log(f"⏸ Account STOPPED by user.", "warning", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_start_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        bot_state.resume(uid)
        if "on_start_account" in bot_state.refresh_callbacks:
            await bot_state.refresh_callbacks["on_start_account"](uid)
        bot_state.log(f"▶ Account STARTED by user.", "success", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_get("/api/account/detail", handle_get_account_detail)   # 🔥 NEW
    app.router.add_get("/api/logs", handle_get_global_logs)                # 🔥 NEW
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/stop", handle_stop_account)
    app.router.add_post("/api/account/start", handle_start_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")
