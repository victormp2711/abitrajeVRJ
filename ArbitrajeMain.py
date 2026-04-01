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
    return {"minimum_profit": min_profit}

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

def calculate_differences(binance_prices, kraken_prices, bybit_prices, huobi_prices, investment_usdt=100):
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

        differences.append({
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
            "profit": profit
        })

    # Ordenar por ganancia (de mayor a menor)
    differences.sort(key=lambda x: x["profit"], reverse=True)

    return differences

def print_differences(differences, minimum_profit):
    print(
        f"Oportunidades de arbitraje (inversión {STAKE_USDT:g} USDT por par, ganancia >= {minimum_profit} USDT):"
    )
    print("-" * 220)
    print(
        f"{'Moneda':<10} {'Binance (USDT)':>15} {'Kraken (USD)':>15} {'Bybit (USDT)':>15} {'Huobi (USDT)':>15} "
        f"{'Comprar en':>10} {'Precio compra':>15} {'Vender en':>10} {'Precio venta':>15} "
        f"{'Cantidad comprada':>15} {'Monto vendido':>15} {'Ganancia (USDT)':>15}"
    )
    print("-" * 220)

    if not differences:
        print("(Ninguna oportunidad cumple el umbral de ganancia mínima.)")
        return

    for diff in differences:
        if diff["profit"] >= minimum_profit:
            print(
                f"{diff['symbol']:<10} {diff['binance_price']:>15.6f} {diff['kraken_price']:>15.6f} "
                f"{diff['bybit_price']:>15.6f} {diff['huobi_price']:>15.6f} {diff['buy_at']:>10} "
                f"{diff['buy_price']:>15.6f} {diff['sell_at']:>10} {diff['sell_price']:>15.6f} "
                f"{diff['amount_bought']:>15.6f} {diff['amount_sold']:>15.6f} {diff['profit']:>15.6f}"
            )

if __name__ == "__main__":
    try:
        cfg = load_config()
        min_profit = cfg["minimum_profit"]

        binance_prices = get_binance_prices()
        kraken_prices = get_kraken_prices()
        bybit_prices = get_bybit_prices()
        huobi_prices = get_huobi_prices()

        differences = calculate_differences(
            binance_prices, kraken_prices, bybit_prices, huobi_prices, investment_usdt=STAKE_USDT
        )
        filtered = [d for d in differences if d["profit"] >= min_profit]
        print_differences(filtered, min_profit)
    except requests.exceptions.RequestException as e:
        print(f"Error al conectar con las APIs: {e}")