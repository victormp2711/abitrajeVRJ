import configparser
import os
import requests

# Capital fijo por fila de arbitraje (cálculo de cantidades y ganancia en USDT).
STAKE_USDT = 100.0

def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arbitraje.ini")
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["DEFAULT"]
    # El .ini usa minimun_profit (ortografía del archivo)
    min_profit = float(section.get("minimun_profit", section.get("minimum_profit", "0")))
    require_transfer = section.get("require_active_transfer", "0").strip().startswith("1")
    return {"minimum_profit": min_profit, "require_active_transfer": require_transfer}


def _kraken_base_to_symbol(base: str) -> str:
    m = {"XXBT": "BTC", "XETH": "ETH", "XXDG": "DOGE", "XDG": "DOGE", "XXRP": "XRP"}
    return m.get(base, base)


def _kraken_alt_to_symbol(altname: str) -> str:
    al = (altname or "").upper()
    if al == "XBT":
        return "BTC"
    if al == "XDG":
        return "DOGE"
    return al


def fetch_binance_spot_trading_map():
    r = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=90)
    r.raise_for_status()
    out = {}
    for s in r.json()["symbols"]:
        sym = s["symbol"]
        if not sym.endswith("USDT"):
            continue
        base = sym[:-4]
        ok = s.get("status") == "TRADING"
        perms = s.get("permissions") or []
        if perms:
            ok = ok and "SPOT" in perms
        out[base] = ok
    return out


def fetch_huobi_spot_trading_map():
    r = requests.get("https://api.huobi.pro/v1/common/symbols", timeout=90)
    r.raise_for_status()
    out = {}
    for s in r.json()["data"]:
        sym = s.get("symbol", "")
        if not sym.endswith("usdt"):
            continue
        base = sym[:-4].upper()
        ok = s.get("state") == "online" and s.get("api-trading") == "enabled"
        out[base] = ok
    return out


def fetch_huobi_deposit_map():
    r = requests.get("https://api.huobi.pro/v2/reference/currencies", timeout=120)
    r.raise_for_status()
    out = {}
    for cur in r.json().get("data") or []:
        ccy = (cur.get("currency") or "").upper()
        inst_ok = cur.get("instStatus") == "normal"
        chains = cur.get("chains") or []
        dep_ok = any(ch.get("depositStatus") == "allowed" for ch in chains)
        out[ccy] = inst_ok and dep_ok
    return out


def fetch_kraken_tradable_bases_usd():
    r = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=90)
    r.raise_for_status()
    bases = set()
    quotes = {"ZUSD", "ZUSDT", "USDT", "USDC", "DAI"}
    for info in r.json()["result"].values():
        if info.get("status") != "online":
            continue
        if info.get("quote") not in quotes:
            continue
        bases.add(_kraken_base_to_symbol(info["base"]))
    return bases


def fetch_kraken_deposit_enabled_map():
    r = requests.get("https://api.kraken.com/0/public/Assets", timeout=90)
    r.raise_for_status()
    out = {}
    for aid, info in r.json()["result"].items():
        norm = _kraken_alt_to_symbol(info.get("altname") or aid)
        enabled = info.get("status") == "enabled"
        if norm not in out:
            out[norm] = enabled
        else:
            out[norm] = out[norm] or enabled
    return out


def fetch_bybit_linear_trading_map():
    out = {}
    cursor = None
    while True:
        params = {"category": "linear", "limit": 500}
        if cursor:
            params["cursor"] = cursor
        r = requests.get("https://api.bybit.com/v5/market/instruments-info", params=params, timeout=90)
        r.raise_for_status()
        body = r.json()
        if body.get("retCode") != 0:
            raise RuntimeError(body.get("retMsg", "Bybit instruments-info"))
        lst = body["result"]["list"]
        for row in lst:
            sym = row.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            base = sym[:-4]
            out[base] = row.get("status") == "Trading"
        cursor = body["result"].get("nextPageCursor") or ""
        if not cursor:
            break
    return out


def fetch_exchange_availability():
    print("Cargando estado de mercado (compra spot/perp y depósitos públicos)...")
    return {
        "binance_spot": fetch_binance_spot_trading_map(),
        "huobi_spot": fetch_huobi_spot_trading_map(),
        "huobi_deposit": fetch_huobi_deposit_map(),
        "kraken_tradable": fetch_kraken_tradable_bases_usd(),
        "kraken_deposit": fetch_kraken_deposit_enabled_map(),
        "bybit_linear": fetch_bybit_linear_trading_map(),
    }


def buy_market_active(exchange: str, symbol: str, av: dict) -> bool:
    s = symbol.upper()
    if exchange == "Binance":
        return av["binance_spot"].get(s, False)
    if exchange == "Huobi":
        return av["huobi_spot"].get(s, False)
    if exchange == "Kraken":
        return s in av["kraken_tradable"]
    if exchange == "Bybit":
        return av["bybit_linear"].get(s, False)
    return False


def sell_exchange_deposit_active(exchange: str, symbol: str, av: dict):
    """
    True/False si la API pública indica depósitos permitidos para el activo.
    None = no verificable sin API key (Binance) o no aplica igual que spot (Bybit perp USDT-m).
    """
    s = symbol.upper()
    if exchange == "Binance":
        return None
    if exchange == "Huobi":
        return av["huobi_deposit"].get(s, False)
    if exchange == "Kraken":
        return av["kraken_deposit"].get(s, False)
    if exchange == "Bybit":
        return None
    return None


def attach_transfer_flags(diff: dict, av: dict) -> None:
    buy_ex = diff["buy_at"]
    sell_ex = diff["sell_at"]
    sym = diff["symbol"]
    buy_ok = buy_market_active(buy_ex, sym, av)
    dep = sell_exchange_deposit_active(sell_ex, sym, av)
    diff["buy_market_ok"] = buy_ok
    diff["sell_deposit_ok"] = dep
    if not buy_ok:
        diff["transfer_route_ok"] = False
    elif dep is True:
        diff["transfer_route_ok"] = True
    elif dep is False:
        diff["transfer_route_ok"] = False
    else:
        diff["transfer_route_ok"] = None

def get_binance_prices():
    print("Getting Binance prices...")
    url = "https://api.binance.com/api/v3/ticker/24hr"
    response = requests.get(url)
    response.raise_for_status()
    tickers = response.json()

    # Filtrar solo pares en USDT con volumen significativo y precio válido
    usdt_pairs = [
        ticker for ticker in tickers
        if ticker["symbol"].endswith("USDT")
        and float(ticker["volume"]) > 1000  # Filtrar monedas con bajo volumen
        and float(ticker["lastPrice"]) > 0.001  # Filtrar precios muy bajos
    ]
    sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x["volume"]), reverse=True)

    # Tomar las primeras 150 monedas
    top_150 = sorted_pairs[:150]

    # Crear un diccionario con los precios: {symbol: price}
    binance_prices = {}
    for ticker in top_150:
        symbol = ticker["symbol"].replace("USDT", "")  # Ejemplo: "BTCUSDT" -> "BTC"
        price = float(ticker["lastPrice"])
        binance_prices[symbol] = price

    return binance_prices

def get_kraken_prices():
    print("Getting Kraken prices...")
    url = "https://api.kraken.com/0/public/Ticker"
    response = requests.get(url)
    response.raise_for_status()
    tickers = response.json()["result"]

    # Crear un diccionario con los precios: {symbol: price}
    kraken_prices = {}
    for symbol, data in tickers.items():
        if symbol.endswith("USD") or symbol.endswith("USDT"):
            # Normalizar símbolos de Kraken a Binance
            normalized_symbol = (
                symbol.replace("XBT", "BTC")
                      .replace("XDG", "DOGE")
                      .replace("USDT", "")
                      .replace("USD", "")
                      .replace("USDC", "")
            )
            price = float(data["c"][0])  # Precio actual
            if price > 0.001:  # Filtrar precios muy bajos
                kraken_prices[normalized_symbol] = price

    return kraken_prices

def get_bybit_prices():
    print("Getting Bybit prices...")
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    response = requests.get(url)
    response.raise_for_status()
    tickers = response.json()

    # Crear un diccionario con los precios: {symbol: price}
    bybit_prices = {}
    for ticker in tickers["result"]["list"]:
        if ticker["symbol"].endswith("USDT"):
            symbol = ticker["symbol"].replace("USDT", "")
            price = float(ticker["lastPrice"])
            if price > 0.001:  # Filtrar precios muy bajos
                bybit_prices[symbol] = price

    return bybit_prices

def get_huobi_prices():
    print("Getting Huobi prices...")
    url = "https://api.huobi.pro/market/tickers"
    response = requests.get(url)
    response.raise_for_status()
    tickers = response.json()

    # Crear un diccionario con los precios: {symbol: price}
    huobi_prices = {}
    for ticker in tickers["data"]:
        if ticker["symbol"].endswith("usdt"):
            symbol = ticker["symbol"].replace("usdt", "").upper()  # Huobi usa minúsculas
            price = float(ticker["close"])
            if price > 0.001:  # Filtrar precios muy bajos
                huobi_prices[symbol] = price

    return huobi_prices

def calculate_differences(
    binance_prices,
    kraken_prices,
    bybit_prices,
    huobi_prices,
    investment_usdt=100,
    availability=None,
):
    # Encontrar las monedas comunes en los cuatro exchanges
    common_symbols = set(binance_prices.keys()) & set(kraken_prices.keys()) & set(bybit_prices.keys()) & set(huobi_prices.keys())

    # Filtrar monedas con nombres muy cortos (ejemplo: "G", "D")
    common_symbols = [s for s in common_symbols if len(s) > 1]

    # Calcular las diferencias porcentuales y recomendar dónde comprar/vender
    differences = []
    for symbol in common_symbols:
        prices = {
            "Binance": binance_prices[symbol],
            "Kraken": kraken_prices[symbol],
            "Bybit": bybit_prices[symbol],
            "Huobi": huobi_prices[symbol]
        }

        # Calcular diferencias porcentuales
        difference_binance_kraken = ((prices["Kraken"] - prices["Binance"]) / prices["Binance"]) * 100
        difference_binance_bybit = ((prices["Bybit"] - prices["Binance"]) / prices["Binance"]) * 100
        difference_binance_huobi = ((prices["Huobi"] - prices["Binance"]) / prices["Binance"]) * 100
        difference_kraken_bybit = ((prices["Bybit"] - prices["Kraken"]) / prices["Kraken"]) * 100
        difference_kraken_huobi = ((prices["Huobi"] - prices["Kraken"]) / prices["Kraken"]) * 100
        difference_bybit_huobi = ((prices["Huobi"] - prices["Bybit"]) / prices["Bybit"]) * 100

        # Determinar dónde comprar (precio más bajo) y dónde vender (precio más alto)
        buy_at = min(prices, key=prices.get)
        sell_at = max(prices, key=prices.get)
        buy_price = prices[buy_at]
        sell_price = prices[sell_at]

        amount_bought = investment_usdt / buy_price
        amount_sold = amount_bought * sell_price
        profit = amount_sold - investment_usdt

        row = {
            "symbol": symbol,
            "binance_price": prices["Binance"],
            "kraken_price": prices["Kraken"],
            "bybit_price": prices["Bybit"],
            "huobi_price": prices["Huobi"],
            "difference_binance_kraken": difference_binance_kraken,
            "difference_binance_bybit": difference_binance_bybit,
            "difference_binance_huobi": difference_binance_huobi,
            "difference_kraken_bybit": difference_kraken_bybit,
            "difference_kraken_huobi": difference_kraken_huobi,
            "difference_bybit_huobi": difference_bybit_huobi,
            "buy_at": buy_at,
            "sell_at": sell_at,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "amount_bought": amount_bought,
            "amount_sold": amount_sold,
            "profit": profit,
        }
        if availability is not None:
            attach_transfer_flags(row, availability)
        differences.append(row)

    # Ordenar por ganancia (de mayor a menor)
    differences.sort(key=lambda x: x["profit"], reverse=True)

    return differences

def _fmt_tri(v):
    if v is True:
        return "Si"
    if v is False:
        return "No"
    return "N/D"


def _arbitraje_valido_si_no(diff: dict) -> str:
    """Si = compra operativa y depósito en venta confirmados por API pública."""
    return "Si" if diff.get("transfer_route_ok") is True else "No"


def print_differences(differences, minimum_profit):
    print(
        f"Oportunidades de arbitraje (inversión {STAKE_USDT:g} USDT por par, ganancia >= {minimum_profit} USDT):"
    )
    print(
        "Compra OK = mercado operativo en broker de compra; Dep venta = depósito del activo permitido (API pública). "
        "N/D en Binance (sin API key) y Bybit (perp USDT-m, no equivale a depósito on-chain del mismo criterio). "
        "Válido = Si solo si Ruta verificable completa (misma condición que columna Ruta = Si)."
    )
    print("-" * 272)
    print(
        f"{'Moneda':<10} {'Binance':>12} {'Kraken':>12} {'Bybit':>12} {'Huobi':>12} "
        f"{'Comprar':>8} {'P.compra':>12} {'Vender':>8} {'P.venta':>12} "
        f"{'Ganancia':>12} {'Cpra OK':>7} {'Dep.Vta':>7} {'Ruta':>5} {'Valido':>7}"
    )
    print("-" * 272)

    if not differences:
        print("(Ninguna oportunidad cumple el umbral de ganancia mínima.)")
        return

    for diff in differences:
        if diff["profit"] >= minimum_profit:
            buy_m = diff.get("buy_market_ok")
            dep = diff.get("sell_deposit_ok")
            route = diff.get("transfer_route_ok")
            print(
                f"{diff['symbol']:<10} {diff['binance_price']:>12.6f} {diff['kraken_price']:>12.6f} "
                f"{diff['bybit_price']:>12.6f} {diff['huobi_price']:>12.6f} {diff['buy_at']:>8} "
                f"{diff['buy_price']:>12.6f} {diff['sell_at']:>8} {diff['sell_price']:>12.6f} "
                f"{diff['profit']:>12.6f} {_fmt_tri(buy_m):>7} {_fmt_tri(dep):>7} "
                f"{_fmt_tri(route):>5} {_arbitraje_valido_si_no(diff):>7}"
            )

if __name__ == "__main__":
    try:
        cfg = load_config()
        min_profit = cfg["minimum_profit"]
        require_transfer = cfg["require_active_transfer"]

        binance_prices = get_binance_prices()
        kraken_prices = get_kraken_prices()
        bybit_prices = get_bybit_prices()
        huobi_prices = get_huobi_prices()
        availability = fetch_exchange_availability()

        differences = calculate_differences(
            binance_prices,
            kraken_prices,
            bybit_prices,
            huobi_prices,
            investment_usdt=STAKE_USDT,
            availability=availability,
        )
        filtered = [d for d in differences if d["profit"] >= min_profit]
        if require_transfer:
            filtered = [d for d in filtered if d.get("transfer_route_ok") is True]
        print_differences(filtered, min_profit)
    except requests.exceptions.RequestException as e:
        print(f"Error al conectar con las APIs: {e}")