from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from audit.aletheia_wrapper import AletheiaWrapper


class DataManager:
    SUPPORTED_BACKENDS = ("yfinance", "polygon", "fmp", "alpha_vantage")

    def __init__(
        self,
        cache_dir: str | Path = ".cache/backtesting",
        backend_order: list[str] | None = None,
        polygon_api_key: str | None = None,
        fmp_api_key: str | None = None,
        alpha_vantage_api_key: str | None = None,
        gateway_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.backend_order = self._clean_backend_order(backend_order or self._env_backend_order())
        self.polygon_api_key = polygon_api_key or os.getenv("POLYGON_API_KEY", "")
        self.fmp_api_key = fmp_api_key or os.getenv("FMP_API_KEY", "")
        self.alpha_vantage_api_key = alpha_vantage_api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.auditor = AletheiaWrapper(gateway_url=gateway_url, api_key=api_key)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        cleaned = symbol.strip().upper()
        mapping = {
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
            "BTCUSD": "BTC-USD",
            "ETHUSD": "ETH-USD",
        }
        if cleaned in mapping:
            return mapping[cleaned]
        if "/" in cleaned:
            left, right = cleaned.split("/", 1)
            return f"{left}{right}=X"
        return cleaned

    @staticmethod
    def period_to_date_range(
        period: str,
        *,
        end: datetime | None = None,
    ) -> tuple[str, str]:
        now = end or datetime.now(UTC)
        period_lower = period.strip().lower()
        amount = ""
        unit = ""
        for char in period_lower:
            if char.isdigit():
                amount += char
            else:
                unit += char
        value = int(amount or "1")

        if unit in {"d", "day", "days"}:
            delta = pd.Timedelta(days=value)
        elif unit in {"wk", "w", "week", "weeks"}:
            delta = pd.Timedelta(weeks=value)
        elif unit in {"mo", "mon", "month", "months"}:
            delta = pd.Timedelta(days=30 * value)
        elif unit in {"y", "yr", "year", "years"}:
            delta = pd.Timedelta(days=365 * value)
        else:
            delta = pd.Timedelta(days=value)

        start = now - delta
        return start.date().isoformat(), now.date().isoformat()

    def download(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        use_cache: bool = True,
        backend_order: list[str] | None = None,
    ) -> pd.DataFrame:
        normalized = self.normalize_symbol(symbol)
        resolved_backends = self._clean_backend_order(backend_order or self.backend_order)
        cache_key = hashlib.sha1(
            f"{normalized}|{timeframe}|{start}|{end}|{'|'.join(resolved_backends)}".encode()
        ).hexdigest()[:16]
        cache_file = self.cache_dir / f"{normalized.replace('/', '_')}_{timeframe}_{cache_key}.pkl"

        if use_cache and cache_file.exists():
            cached = pd.read_pickle(cache_file)
            if isinstance(cached, pd.DataFrame):
                cached.attrs.setdefault("source_backend", "cache")
                return cached

        failures: dict[str, str] = {}
        for backend in resolved_backends:
            if not self._backend_enabled(backend):
                failures[backend] = "backend not configured"
                continue

            try:
                raw = self._fetch_from_backend(
                    backend=backend,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )
            except Exception as exc:
                failures[backend] = str(exc)
                continue

            data = self._normalize_ohlcv(raw)
            if data.empty:
                failures[backend] = "empty dataset"
                continue

            data.attrs["source_backend"] = backend
            data.attrs["source_symbol"] = normalized
            if use_cache:
                data.to_pickle(cache_file)
            self._audit_market_data_decision(
                symbol=normalized,
                timeframe=timeframe,
                start=start,
                end=end,
                backend_order=resolved_backends,
                selected_backend=backend,
                failures=failures,
                cache_hit=False,
            )
            return data

        synthetic = self._synthetic_ohlcv(start=start, end=end, timeframe=timeframe)
        synthetic.attrs["source_backend"] = "synthetic"
        synthetic.attrs["source_symbol"] = normalized
        self._audit_market_data_decision(
            symbol=normalized,
            timeframe=timeframe,
            start=start,
            end=end,
            backend_order=resolved_backends,
            selected_backend="synthetic",
            failures=failures,
            cache_hit=False,
        )
        return synthetic

    @staticmethod
    def _env_backend_order() -> list[str]:
        raw = os.getenv("MARKET_DATA_BACKENDS", "")
        if not raw:
            return ["yfinance", "polygon", "fmp", "alpha_vantage"]
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    def _clean_backend_order(self, backend_order: list[str]) -> list[str]:
        deduped: list[str] = []
        for backend in backend_order:
            cleaned = backend.strip().lower()
            if cleaned in self.SUPPORTED_BACKENDS and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped or ["yfinance"]

    def _backend_enabled(self, backend: str) -> bool:
        if backend == "yfinance":
            return True
        if backend == "polygon":
            return bool(self.polygon_api_key)
        if backend == "fmp":
            return bool(self.fmp_api_key)
        if backend == "alpha_vantage":
            return bool(self.alpha_vantage_api_key)
        return False

    def _fetch_from_backend(
        self,
        *,
        backend: str,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        if backend == "yfinance":
            return self._fetch_yfinance(symbol=symbol, timeframe=timeframe, start=start, end=end)
        if backend == "polygon":
            return self._fetch_polygon(symbol=symbol, timeframe=timeframe, start=start, end=end)
        if backend == "fmp":
            return self._fetch_fmp(symbol=symbol, timeframe=timeframe, start=start, end=end)
        if backend == "alpha_vantage":
            return self._fetch_alpha_vantage(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
            )
        raise ValueError(f"Unsupported backend: {backend}")

    def _fetch_yfinance(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        data = pd.DataFrame()
        for candidate in self._symbol_candidates(symbol):
            data = yf.download(
                candidate,
                interval=timeframe,
                start=start,
                end=end,
                auto_adjust=False,
                progress=False,
            )
            if not data.empty:
                return data
        return data

    def _fetch_polygon(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        multiplier, timespan = self._polygon_timespan(timeframe)
        polygon_symbol = self._polygon_symbol(symbol)
        response = requests.get(
            (
                "https://api.polygon.io/v2/aggs/ticker/"
                f"{polygon_symbol}/range/{multiplier}/{timespan}/{start}/{end}"
            ),
            params={
                "adjusted": "true",
                "sort": "asc",
                "limit": 50000,
                "apiKey": self.polygon_api_key,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results", [])
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).rename(
            columns={
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "t": "timestamp",
            }
        )

    def _fetch_fmp(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        interval = self._fmp_interval(timeframe)
        normalized = self.normalize_symbol(symbol).replace("=X", "")
        if interval == "1day":
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{normalized}"
            params: dict[str, Any] = {
                "from": start,
                "to": end,
                "apikey": self.fmp_api_key,
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("historical", [])
        else:
            url = (
                f"https://financialmodelingprep.com/api/v3/historical-chart/{interval}/{normalized}"
            )
            params = {"from": start, "to": end, "apikey": self.fmp_api_key}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            rows = response.json()

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def _fetch_alpha_vantage(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        del start, end
        normalized = self.normalize_symbol(symbol)
        params: dict[str, str] = {"apikey": self.alpha_vantage_api_key, "outputsize": "full"}

        if timeframe.lower() in {"1d", "d", "day", "daily"}:
            if self._is_fx_symbol(normalized):
                from_symbol, to_symbol = self._split_fx_pair(normalized)
                params.update(
                    {
                        "function": "FX_DAILY",
                        "from_symbol": from_symbol,
                        "to_symbol": to_symbol,
                    }
                )
                data_key = "Time Series FX (Daily)"
            else:
                params.update(
                    {
                        "function": "TIME_SERIES_DAILY_ADJUSTED",
                        "symbol": normalized.replace("=X", ""),
                    }
                )
                data_key = "Time Series (Daily)"
        else:
            av_interval = self._alpha_vantage_interval(timeframe)
            if self._is_fx_symbol(normalized):
                from_symbol, to_symbol = self._split_fx_pair(normalized)
                params.update(
                    {
                        "function": "FX_INTRADAY",
                        "from_symbol": from_symbol,
                        "to_symbol": to_symbol,
                        "interval": av_interval,
                    }
                )
                data_key = f"Time Series FX ({av_interval})"
            else:
                params.update(
                    {
                        "function": "TIME_SERIES_INTRADAY",
                        "symbol": normalized.replace("=X", ""),
                        "interval": av_interval,
                        "adjusted": "true",
                    }
                )
                data_key = f"Time Series ({av_interval})"

        response = requests.get("https://www.alphavantage.co/query", params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if data_key not in payload:
            return pd.DataFrame()

        rows = []
        for timestamp, values in payload[data_key].items():
            rows.append(
                {
                    "timestamp": timestamp,
                    "open": values.get("1. open"),
                    "high": values.get("2. high"),
                    "low": values.get("3. low"),
                    "close": values.get("4. close"),
                    "volume": values.get("5. volume", 0.0),
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _normalize_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
        if data.empty:
            return data

        out = data.copy()
        if isinstance(out.columns, pd.MultiIndex):
            out.columns = [str(column[0]) for column in out.columns]

        out.columns = [str(column).strip() for column in out.columns]
        renamed = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "close",
            "Volume": "volume",
            "date": "timestamp",
        }
        out = out.rename(columns=renamed)

        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
            out = out.set_index("timestamp")
        elif "Date" in out.columns:
            out["Date"] = pd.to_datetime(out["Date"], utc=True)
            out = out.set_index("Date")
        else:
            out.index = pd.to_datetime(out.index, utc=True)

        for column in ["open", "high", "low", "close", "volume"]:
            if column not in out.columns:
                out[column] = 0.0

        out = out[["open", "high", "low", "close", "volume"]].copy()
        out = out.apply(pd.to_numeric, errors="coerce").dropna(
            subset=["open", "high", "low", "close"]
        )
        out["volume"] = out["volume"].fillna(0.0)
        out = out.sort_index()
        return out

    def _symbol_candidates(self, symbol: str) -> list[str]:
        cleaned = symbol.strip().upper()
        normalized = self.normalize_symbol(symbol)
        candidates = [normalized]

        fallback = {
            "EURUSD": "FXE",
            "EURUSD=X": "FXE",
            "GBPUSD": "FXB",
            "GBPUSD=X": "FXB",
            "USDJPY": "FXY",
            "JPY=X": "FXY",
        }

        if cleaned in fallback:
            candidates.append(fallback[cleaned])
        if normalized in fallback:
            candidates.append(fallback[normalized])

        deduped: list[str] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _polygon_timespan(timeframe: str) -> tuple[int, str]:
        mapping = {
            "1m": (1, "minute"),
            "5m": (5, "minute"),
            "15m": (15, "minute"),
            "30m": (30, "minute"),
            "1h": (1, "hour"),
            "60m": (1, "hour"),
            "1d": (1, "day"),
        }
        return mapping.get(timeframe.lower(), (1, "day"))

    @staticmethod
    def _fmp_interval(timeframe: str) -> str:
        mapping = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1hour",
            "60m": "1hour",
            "4h": "4hour",
            "1d": "1day",
        }
        return mapping.get(timeframe.lower(), "1day")

    @staticmethod
    def _alpha_vantage_interval(timeframe: str) -> str:
        mapping = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "60min",
            "60m": "60min",
        }
        return mapping.get(timeframe.lower(), "60min")

    @staticmethod
    def _polygon_symbol(symbol: str) -> str:
        normalized = DataManager.normalize_symbol(symbol)
        if DataManager._is_fx_symbol(normalized):
            left, right = DataManager._split_fx_pair(normalized)
            return f"C:{left}{right}"
        if normalized.endswith("-USD"):
            return f"X:{normalized.replace('-', '')}"
        return normalized.replace("=X", "")

    @staticmethod
    def _is_fx_symbol(symbol: str) -> bool:
        normalized = symbol.replace("=X", "")
        return len(normalized) == 6 and normalized.isalpha()

    @staticmethod
    def _split_fx_pair(symbol: str) -> tuple[str, str]:
        normalized = symbol.replace("=X", "")
        if normalized == "JPY":
            return "USD", "JPY"
        return normalized[:3], normalized[3:6]

    @staticmethod
    def _synthetic_ohlcv(start: str, end: str, timeframe: str) -> pd.DataFrame:
        tf = timeframe.lower()
        freq_map = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1h",
            "60m": "1h",
            "4h": "4h",
            "1d": "1d",
        }
        freq = freq_map.get(tf, "1h")

        idx = pd.date_range(start=start, end=end, freq=freq, tz="UTC")
        if len(idx) < 250:
            idx = pd.date_range(start=start, periods=500, freq="1h", tz="UTC")

        base = np.linspace(100.0, 120.0, len(idx))
        wave = np.sin(np.linspace(0, 24, len(idx))) * 2.0
        close = base + wave

        df = pd.DataFrame(index=idx)
        df["close"] = close
        df["open"] = df["close"].shift(1).fillna(df["close"])
        df["high"] = df[["open", "close"]].max(axis=1) * 1.001
        df["low"] = df[["open", "close"]].min(axis=1) * 0.999
        df["volume"] = 10_000
        return df

    def _audit_market_data_decision(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: str,
        end: str,
        backend_order: list[str],
        selected_backend: str,
        failures: dict[str, str],
        cache_hit: bool,
    ) -> None:
        try:
            self.auditor.audit(
                action="market_data_request",
                payload={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "start": start,
                    "end": end,
                    "backend_order": backend_order,
                    "selected_backend": selected_backend,
                    "backend_failures": failures,
                    "cache_hit": cache_hit,
                },
                policy_pack="market_data",
            )
        except Exception:
            return


DataDownloader = DataManager
