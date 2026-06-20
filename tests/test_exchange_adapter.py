"""
test_exchange_adapter.py — Tests del adaptador CCXTExchange.

No tocan Binance: usan un cliente CCXT falso y verifican que el adaptador
MAPEE y NORMALICE bien (filtros, balances, lookup por clientOrderId, venta a
mercado). La lógica de negocio se prueba en los otros módulos.
"""

from exchange import CCXTExchange


BINANCE_FILTERS = [
    {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001"},
    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000.00"},
    {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
]


class FakeCCXT:
    def __init__(self):
        self.load_calls = 0
        self.created = []
        self.fetch_order_args = None

    def load_markets(self):
        self.load_calls += 1
        return {}

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return [[i, 0, 0, 0, 100 + i, 0] for i in range(limit)]

    def fetch_balance(self):
        return {"total": {"BTC": 0.5, "USDT": 1000.0},
                "free": {"BTC": 0.4, "USDT": 800.0}}

    def market(self, symbol):
        return {"info": {"filters": BINANCE_FILTERS}}

    def fetch_ticker(self, symbol):
        return {"last": 50000.0}

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        self.created.append((symbol, type, side, amount, price, params))
        return {"status": "closed", "filled": amount, "clientOrderId": "x"}

    def fetch_order(self, id, symbol, params=None):
        self.fetch_order_args = (id, symbol, params)
        return {"status": "closed", "filled": 0.1, "clientOrderId": "bot-abc"}

    def cancel_all_orders(self, symbol):
        return [{"id": "1"}]


def adapter():
    return CCXTExchange(FakeCCXT(), "BTC/USDT")


# ── Filtros de mercado ─────────────────────────────────────────────

def test_market_filters_parsea_binance():
    ex = adapter()
    f = ex.market_filters("BTC/USDT")
    assert f["step_size"] == 0.00001
    assert f["min_notional"] == 5.0
    assert f["min_price"] == 0.01
    assert f["max_price"] == 1000000.0
    assert f["ref_price"] == 50000.0  # del ticker


# ── Balances ───────────────────────────────────────────────────────

def test_base_balance_usa_total():
    assert adapter().fetch_base_balance("BTC/USDT") == 0.5


def test_quote_balance_usa_free():
    assert adapter().fetch_quote_balance("BTC/USDT") == 800.0


# ── OHLCV y carga de mercados ──────────────────────────────────────

def test_fetch_ohlcv_carga_markets_una_vez():
    client = FakeCCXT()
    ex = CCXTExchange(client, "BTC/USDT")
    ex.fetch_ohlcv("BTC/USDT", "1h", 10)
    ex.fetch_ohlcv("BTC/USDT", "1h", 10)
    assert client.load_calls == 1  # cacheado


# ── Órdenes ────────────────────────────────────────────────────────

def test_fetch_order_busca_por_client_order_id():
    client = FakeCCXT()
    ex = CCXTExchange(client, "BTC/USDT")
    ex.fetch_order("bot-abc", "BTC/USDT")
    id_arg, symbol_arg, params = client.fetch_order_args
    assert id_arg is None  # el lookup va por clientOrderId, no por id numérico
    assert params == {"origClientOrderId": "bot-abc"}


def test_create_market_sell_arma_orden_market():
    client = FakeCCXT()
    ex = CCXTExchange(client, "BTC/USDT")
    ex.create_market_sell("BTC/USDT", 0.25)
    symbol, type_, side, amount, price, params = client.created[0]
    assert (type_, side, amount) == ("market", "sell", 0.25)


def test_cancel_all_orders_devuelve_lista():
    assert adapter().cancel_all_orders("BTC/USDT") == [{"id": "1"}]
