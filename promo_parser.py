import aiohttp
import config

async def fetch_codes_from_url(url):
    codes = set()
    if not url:
        return []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    items = []
                    if isinstance(data, dict):
                        if "active" in data:
                            items = data["active"]
                        elif "CODES" in data:
                            items = data["CODES"]
                    elif isinstance(data, list):
                        items = data

                    for item in items:
                        if isinstance(item, dict):
                            if item.get("is_expired") is True:
                                continue
                            code = item.get("code") or item.get("CODES")
                            if code:
                                codes.add(str(code).strip())
                        elif isinstance(item, str):
                            codes.add(item.strip())
    except Exception:
        pass
    return list(codes)

async def collect_all_promos(log_signal, target_acc_id="ALL"):
    log_signal.emit(target_acc_id, "🌐 Сканируем источники на новые промокоды...")
    
    if not isinstance(config.PROMOS, dict) or "active_codes" not in config.PROMOS:
        config.PROMOS = {"active_codes": {}, "history": {}}

    new_total_added = 0
    for game_key, game_info in config.GAMES.items():
        url = game_info.get("promo_url", "").strip()
        short = game_info.get("short_name", game_key)
        
        if not url:
            continue
            
        codes = await fetch_codes_from_url(url)
        current_active = set(config.PROMOS["active_codes"].get(game_key, []))
        fresh_active = set(codes)
        new_codes = fresh_active - current_active
        config.PROMOS["active_codes"][game_key] = codes
        
        if new_codes:
            log_signal.emit(target_acc_id, f"  📥 {short}: найдено {len(new_codes)} новых кодов! (Всего: {len(codes)})")
            new_total_added += len(new_codes)
        else:
            log_signal.emit(target_acc_id, f"  📥 {short}: новых кодов нет. Актуальных: {len(codes)} шт.")
    
    config.update_promos(config.PROMOS)
    if new_total_added > 0:
        log_signal.emit(target_acc_id, f"✨ <b>База обновлена! Новых кодов: {new_total_added}.</b>")
    else:
        log_signal.emit(target_acc_id, "✨ <b>База данных актуальна.</b>")