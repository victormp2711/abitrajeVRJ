from datetime import datetime

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ArbitrajeMain import (
    STAKE_USDT,
    _arbitraje_valido_si_no,
    calculate_differences,
    fetch_exchange_availability,
    get_binance_prices,
    get_bybit_prices,
    get_huobi_prices,
    get_kraken_prices,
    load_config,
)


OUTPUT_FILE = "arbitraje_diagrama.pdf"


def build_story():
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]
    mono_style = ParagraphStyle(
        name="MonoSmall",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=9,
        leading=12,
    )

    cfg = load_config()
    minimum_profit = cfg["minimum_profit"]
    require_transfer = cfg.get("require_active_transfer", False)

    story = []
    story.append(Paragraph("Diagrama de Arbitraje entre Binance, Kraken y Bybit", title_style))
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
            f"Stake fijo: {STAKE_USDT:g} USDT | "
            f"Filtro: profit >= {minimum_profit}",
            body_style,
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph("1) Flujo general", heading_style))
    story.append(
        Paragraph(
            "El sistema toma precios de los 3 brokers para el mismo activo, "
            "compra donde esta mas barato y vende donde esta mas caro.",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Preformatted(
            """[Binance] ----\\
[Kraken ] -----+--> [Comparar precios] --> [Compra: precio mas bajo]
[Bybit  ] ----/                           --> [Venta : precio mas alto]""",
            mono_style,
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"2) Flujo de dinero (stake fijo: {STAKE_USDT:g} USDT)", heading_style))
    story.append(
        Preformatted(
            f"""[Capital inicial: {STAKE_USDT:g} USDT]
            |
            v
[Comprar activo en exchange A (menor precio)]
            |
            v
[Vender activo en exchange B (mayor precio)]
            |
            v
[USDT final = Monto vendido]
Ganancia = USDT final - {STAKE_USDT:g}""",
            mono_style,
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph("3) Formula que usa el analisis", heading_style))
    story.append(
        Preformatted(
            f"""amount_bought = {STAKE_USDT:g} / buy_price
amount_sold   = amount_bought * sell_price
profit        = amount_sold - {STAKE_USDT:g}""",
            mono_style,
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph("4) Filtro por ganancia minima", heading_style))
    story.append(
        Paragraph(
            "Solo se muestran oportunidades donde: <b>profit &gt;= minimun_profit</b> "
            "(valor configurado en arbitraje.ini).",
            body_style,
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Nota practica: en mercado real hay comisiones, slippage y tiempos de transferencia.",
            body_style,
        )
    )

    story.append(Spacer(1, 16))
    story.append(Paragraph("5) Oportunidades detectadas en tiempo real", heading_style))
    story.append(Spacer(1, 8))

    try:
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
        filtered = [d for d in differences if d["profit"] >= minimum_profit]
        if require_transfer:
            filtered = [d for d in filtered if d.get("transfer_route_ok") is True]

        if not filtered:
            story.append(
                Paragraph(
                    "No hay oportunidades que cumplan el umbral de ganancia minima.",
                    body_style,
                )
            )
            return story

        rows = [["Moneda", "Comprar", "Vender", "Ganancia", "Cpra OK", "Dep.Vta", "Ruta", "Valido"]]
        for d in filtered[:40]:
            dep = d.get("sell_deposit_ok")
            dep_txt = "Si" if dep is True else ("No" if dep is False else "N/D")
            route = d.get("transfer_route_ok")
            route_txt = "Si" if route is True else ("No" if route is False else "N/D")
            buy_txt = "Si" if d.get("buy_market_ok") else "No"
            rows.append(
                [
                    d["symbol"],
                    d["buy_at"],
                    d["sell_at"],
                    f"{d['profit']:.6f}",
                    buy_txt,
                    dep_txt,
                    route_txt,
                    _arbitraje_valido_si_no(d),
                ]
            )

        table = Table(rows, colWidths=[65, 78, 78, 72, 50, 50, 44, 44], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E3B4E")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ]
            ) 
        )
        story.append(table)
    except requests.exceptions.RequestException as exc:
        story.append(
            Paragraph(
                f"No se pudieron cargar precios en vivo al generar el PDF: {exc}",
                body_style,
            )
        )

    return story


def main():
    doc = SimpleDocTemplate(OUTPUT_FILE, pagesize=A4)
    doc.build(build_story())
    print(f"PDF generado : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
