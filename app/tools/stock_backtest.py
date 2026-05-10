"""Factor testing tool service - market data fetching + code execution sandbox"""
import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import os
from typing import Dict, Any, List, Optional
from app.tools.base import BaseToolService, MCPTool

logger = logging.getLogger(__name__)

# Common index codes
INDEX_NAMES = {
    "000300": "沪深300",
    "000905": "中证500",
    "000016": "上证50",
    "000852": "中证1000",
    "000903": "中证全指",
    "399006": "创业板指",
    "399005": "中小板指",
    "399673": "创业板50",
}

# Preset code injected before user code — provides data and helper functions
PRESET_TEMPLATE = '''
import akshare as ak
import pandas as pd
import numpy as np
from scipy import stats
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
import json
import time
warnings.filterwarnings("ignore")

# ===== Market Data (auto-loaded) =====
_index_code = "__INDEX_CODE__"
_start_date = "__START_DATE__"
_end_date = "__END_DATE__"

# ===== 可用函数列表（详细说明，请仔细阅读后再使用）=====
#
# ---- 行情数据 ----
# 1. get_index_constituents(index_code) -> list[str]
#    返回指数成分股代码列表，如 ["000001", "000002", "600000", ...]
#    ★ 返回值是纯字符串列表，可直接传给 get_batch_prices() 的 symbols 参数
#    示例: codes = get_index_constituents("000300")  # ["000001", "000002", ...]
#
# 2. get_index_data(index_code, start_date, end_date) -> DataFrame
#    ★★★ 获取指数(如沪深300)行情，务必用此函数，不要用 get_stock_prices() ★★★
#    返回 DataFrame，结构如下：
#      索引: DatetimeIndex（日期，如 2024-01-02, 2024-01-03, ...）
#      列:   open, close, high, low, volume, turnover（均为float）
#    示例:
#      df = get_index_data("000300", "20240101", "20241231")
#      df["close"]          # 收盘价 Series
#      df.index             # DatetimeIndex 日期索引
#      df["pct_change"] = df["close"].pct_change()  # 日收益率
#
# 3. get_stock_prices(symbol, start_date, end_date) -> DataFrame
#    ★ 仅用于个股，获取指数行情请用 get_index_data() ★
#    返回 DataFrame，结构如下：
#      索引: DatetimeIndex（日期）
#      列:   open, close, high, low, volume, turnover, pct_change, change, turnover_rate（均为float）
#    示例:
#      df = get_stock_prices("000001", "20240101", "20241231")
#      df["close"]          # 收盘价
#      df["pct_change"]     # 涨跌幅(%)
#
# 4. get_batch_prices(symbols, start_date, end_date, max_stocks=50) -> dict[str, DataFrame]
#    批量获取多只股票行情，返回 {股票代码: DataFrame}，每个DataFrame结构同 get_stock_prices
#    symbols 可直接传入 get_index_constituents() 的返回值
#    示例:
#      codes = get_index_constituents("000300")
#      prices = get_batch_prices(codes, "20240101", "20241231", max_stocks=50)
#      prices["000001"]["close"]  # 某只股票的收盘价 Series
#
# ---- 估值数据 ----
# 5. get_valuation_data(symbol, start_date, end_date) -> DataFrame
#    ★ 获取个股每日估值指标，用于价值因子（PE/PB/PS/股息率）
#    返回 DataFrame，结构如下：
#      索引: DatetimeIndex（日期）
#      列:   pe_ttm, pb, ps_ttm, dv_ratio（均为float）
#    示例:
#      df = get_valuation_data("000001", "20240101", "20241231")
#      df["pe_ttm"]   # 市盈率TTM Series
#      df["pb"]       # 市净率 Series
#
# 6. get_batch_valuation(symbols, start_date, end_date, max_stocks=50) -> dict[str, DataFrame]
#    批量获取估值指标，返回 {股票代码: DataFrame}，每个DataFrame结构同 get_valuation_data
#    示例:
#      val_data = get_batch_valuation(codes, "20240101", "20241231", max_stocks=50)
#
# ---- 财务数据 ----
# 7. get_financial_indicator(symbol, start_year="2020") -> DataFrame
#    ★ 获取个股财务指标（按报告期），用于质量因子（ROE/毛利率/营收增速）
#    返回 DataFrame，每行一个报告期，列包括：
#      date(报告期), roe(净资产收益率%), gross_profit_margin(毛利率%),
#      revenue_yoy(营收同比%), net_profit_yoy(净利润同比%)
#    示例:
#      df = get_financial_indicator("000001", "2020")
#      df["roe"]                 # ROE Series
#      df["gross_profit_margin"] # 毛利率 Series
#
# ---- 行业分类 ----
# 8. get_industry_mapping(symbols=None) -> dict[str, str]
#    ★ 获取股票行业分类映射，用于行业中性化、行业轮动因子
#    首次调用会加载全部行业映射（约需30-60秒），后续使用缓存
#    参数: symbols-股票代码列表（可选，如未提供返回全部A股映射）
#    返回: {"000001": "银行", "000002": "房地产", ...}
#    示例:
#      industries = get_industry_mapping(codes)
#
# ---- 因子测试 ----
# 9.  calc_ic(factor_values, forward_returns) -> float  Pearson IC
# 10. calc_rank_ic(factor_values, forward_returns) -> float  Spearman Rank IC
# 11. factor_group_test(factor_df, n_groups=5) -> dict  因子分组测试
#     factor_df 需要列: date, symbol, factor, forward_return
#
# ★★★ 关键提醒 ★★★
# - 获取指数行情(沪深300/中证500等) → get_index_data()，不要用 get_stock_prices()
# - get_index_constituents() 返回 list[str]，不是 DataFrame
# - 所有 DataFrame 的日期索引是 DatetimeIndex，列名是英文
# - 不需要先"探索数据结构"再写代码，以上列名和索引类型是确定的，直接使用即可

def get_index_constituents(index_code="__INDEX_CODE__"):
    """获取指数成分股代码列表

    返回: list[str]，如 ["000001", "000002", "600000", ...]
    ★ 返回值是纯字符串列表(list)，不是 DataFrame，可直接传给 get_batch_prices()

    示例:
        codes = get_index_constituents("000300")
        prices = get_batch_prices(codes, "20240101", "20241231")
    """
    df = ak.index_stock_cons(symbol=index_code)
    # 自动识别代码列名（akshare不同版本列名不同）
    code_col = None
    for col in df.columns:
        if "代码" in str(col) or "code" in str(col).lower():
            code_col = col
            break
    if code_col is None:
        code_col = df.columns[0]
    return df[code_col].tolist()

def get_stock_prices(symbol, start_date="__START_DATE__", end_date="__END_DATE__", period="daily", retries=3):
    """获取单只股票日线行情

    ★ 仅用于个股，获取指数行情请用 get_index_data()

    参数:
        symbol: 股票代码，如 "000001"
        start_date/end_date: YYYYMMDD格式

    返回: DataFrame，结构确定如下：
        索引: DatetimeIndex（日期，如 2024-01-02）
        列(均为float): open, close, high, low, volume, turnover, pct_change, change, turnover_rate
        - close: 收盘价
        - pct_change: 涨跌幅(%)
        - volume: 成交量
        - turnover: 成交额

    示例:
        df = get_stock_prices("000001", "20240101", "20241231")
        df["close"]          # 收盘价 Series
        df["pct_change"]     # 涨跌幅(%) Series
        df.index[0]          # 第一个日期，如 Timestamp('2024-01-02')
    """
    # 先尝试东方财富源（字段最全）
    for attempt in range(retries):
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period=period,
                                    start_date=start_date, end_date=end_date)
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.set_index("日期")
            col_map = {
                "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "turnover", "振幅": "amplitude",
                "涨跌幅": "pct_change", "涨跌额": "change", "换手率": "turnover_rate"
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            return df
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                break
    # Fallback: 网易源
    try:
        prefix = "sh" if symbol.startswith("6") else "sz"
        df = ak.stock_zh_a_daily(symbol=f"{prefix}{symbol}", start_date=start_date, end_date=end_date)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df.rename(columns={"amount": "turnover"})
        return df
    except Exception as e2:
        print(f"获取 {symbol} 数据失败(东方财富+网易均不通): {e2}")
        return pd.DataFrame()

def get_batch_prices(symbols, start_date="__START_DATE__", end_date="__END_DATE__", max_stocks=50):
    """批量获取多只股票日线行情

    参数:
        symbols: 股票代码列表，如 ["000001", "000002"]。
                 ★ 可直接传入 get_index_constituents() 的返回值（它返回 list[str]）
        max_stocks: 最多获取几只（控制耗时）

    返回: dict[str, DataFrame]，如 {"000001": DataFrame, "000002": DataFrame, ...}
        每个 DataFrame 结构同 get_stock_prices() 的返回值：
        索引 DatetimeIndex，列 open/close/high/low/volume/turnover/pct_change/change/turnover_rate

    示例:
        codes = get_index_constituents("000300")
        prices = get_batch_prices(codes, "20240101", "20241231", max_stocks=50)
        prices["000001"]["close"]  # 000001的收盘价 Series
        for code, df in prices.items():
            print(code, len(df))   # 每只股票的数据行数
    """
    if isinstance(symbols, pd.DataFrame):
        # 兼容：如果传入DataFrame，自动提取代码列
        code_col = None
        for col in symbols.columns:
            if "代码" in str(col) or "code" in str(col).lower():
                code_col = col
                break
        if code_col is None:
            code_col = symbols.columns[0]
        symbols = symbols[code_col].tolist()
    result = {}
    target = symbols[:max_stocks]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(get_stock_prices, sym, start_date, end_date): sym for sym in target}
        for i, future in enumerate(as_completed(futures)):
            sym = futures[future]
            try:
                df = future.result()
                if not df.empty:
                    result[sym] = df
            except:
                pass
            done = i + 1
            if done % 10 == 0:
                print(f"  已获取行情 {done}/{len(target)} 只...")
    print(f"  行情获取完成: {len(result)}/{len(target)} 只")
    return result

def get_index_data(index_code="__INDEX_CODE__", start_date="__START_DATE__", end_date="__END_DATE__"):
    """获取指数本身的日线行情

    ★★★ 获取指数行情务必用此函数，不要用 get_stock_prices()（那是给个股的）★★★

    参数:
        index_code: 指数代码，如 "000300"(沪深300), "000905"(中证500)

    返回: DataFrame，结构确定如下：
        索引: DatetimeIndex（日期，如 2024-01-02, 2024-01-03, ...）
        列(均为float):
            open     - 开盘价
            close    - 收盘价
            high     - 最高价
            low      - 最低价
            volume   - 成交量
            turnover - 成交额
        ★ 列名就是 open/close/high/low/volume/turnover，不需要探索确认

    示例:
        df = get_index_data("000300", "20240101", "20241231")
        df["close"]                              # 收盘价 Series
        df["pct_change"] = df["close"].pct_change()  # 日收益率
        df.index                                 # DatetimeIndex
        df.loc["2024-06-01":"2024-06-30"]        # 按日期切片
    """
    # 先尝试东方财富源
    try:
        df = ak.index_zh_a_hist(symbol=index_code, period="daily",
                                start_date=start_date, end_date=end_date)
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.set_index("日期")
        col_map = {
            "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
            "成交量": "volume", "成交额": "turnover"
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if not df.empty:
            return df
    except Exception:
        pass
    # Fallback: 网易源 (stock_zh_index_daily)
    try:
        prefix = "sh" if index_code.startswith(("0", "9")) else "sz"
        df = ak.stock_zh_index_daily(symbol=f"{prefix}{index_code}")
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        sd = pd.to_datetime(start_date)
        ed = pd.to_datetime(end_date)
        df = df[(df.index >= sd) & (df.index <= ed)]
        df = df.rename(columns={"amount": "turnover"})
        return df
    except Exception as e2:
        print(f"获取指数数据失败(东方财富+网易均不通): {e2}")
        return pd.DataFrame()

# ===== Valuation Data =====
def get_valuation_data(symbol, start_date="__START_DATE__", end_date="__END_DATE__"):
    """获取个股估值指标日线数据 (PE/PB/PS/DV)

    ★ 用于价值因子计算，返回每日估值指标时序

    参数:
        symbol: 股票代码，如 "000001"
        start_date/end_date: YYYYMMDD格式

    返回: DataFrame，结构确定如下：
        索引: DatetimeIndex（日期，如 2024-01-02）
        列(float): pe_ttm(市盈率TTM), pb(市净率), ps_ttm(市销率TTM), dv_ratio(股息率)
        ★ 列名确定，无需探索

    示例:
        df = get_valuation_data("000001", "20240101", "20241231")
        df["pe_ttm"]   # 市盈率TTM Series
        df["pb"]       # 市净率 Series
        df["dv_ratio"] # 股息率 Series
    """
    try:
        df = ak.stock_a_indicator_lg(symbol=symbol)
        if df is None or df.empty:
            return pd.DataFrame()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        sd = pd.to_datetime(start_date)
        ed = pd.to_datetime(end_date)
        df = df[(df.index >= sd) & (df.index <= ed)]
        # Select standard columns
        cols_to_keep = []
        rename_map = {}
        for orig, std in [("pe_ttm", "pe_ttm"), ("pb", "pb"), ("ps_ttm", "ps_ttm"), ("dv_ratio", "dv_ratio")]:
            if orig in df.columns:
                cols_to_keep.append(orig)
                rename_map[orig] = std
        if cols_to_keep:
            return df[cols_to_keep].rename(columns=rename_map)
        return pd.DataFrame()
    except Exception as e:
        print(f"获取 {symbol} 估值数据失败: {e}")
        return pd.DataFrame()

def get_batch_valuation(symbols, start_date="__START_DATE__", end_date="__END_DATE__", max_stocks=50):
    """批量获取多只股票估值指标

    参数:
        symbols: 股票代码列表，如 ["000001", "000002"]
                 可直接传入 get_index_constituents() 的返回值
        start_date/end_date: YYYYMMDD格式
        max_stocks: 最多获取几只（控制耗时）

    返回: dict[str, DataFrame]，如 {"000001": DataFrame, ...}
        每个 DataFrame 结构同 get_valuation_data()

    示例:
        codes = get_index_constituents("000300")
        val_data = get_batch_valuation(codes, "20240101", "20241231", max_stocks=50)
        val_data["000001"]["pe_ttm"]  # 000001的市盈率TTM Series
    """
    result = {}
    target = symbols[:max_stocks]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(get_valuation_data, sym, start_date, end_date): sym for sym in target}
        for i, future in enumerate(as_completed(futures)):
            sym = futures[future]
            try:
                df = future.result()
                if not df.empty:
                    result[sym] = df
            except:
                pass
            done = i + 1
            if done % 10 == 0:
                print(f"  已获取估值数据 {done}/{len(target)} 只...")
    print(f"  估值获取完成: {len(result)}/{len(target)} 只")
    return result

# ===== Financial Data =====
def get_financial_indicator(symbol, start_year="2020"):
    """获取个股财务指标（按报告期）

    ★ 用于质量因子（ROE/毛利率/营收增速等）

    参数:
        symbol: 股票代码，如 "000001"
        start_year: 起始年份，如 "2020"

    返回: DataFrame，每行是一个报告期，列包括：
        date(报告期, datetime), roe(净资产收益率%), gross_profit_margin(毛利率%),
        revenue_yoy(营收同比%), net_profit_yoy(净利润同比%)
        ★ 列名确定，无需探索；不同股票可能有不同列，缺失列为NaN

    示例:
        df = get_financial_indicator("000001", "2020")
        df["roe"]                 # ROE Series
        df["gross_profit_margin"] # 毛利率 Series
        df["revenue_yoy"]         # 营收同比增长率 Series
    """
    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year=start_year)
        if df is None or df.empty:
            return pd.DataFrame()
        # Standardize column names (akshare列名因版本不同可能变化)
        col_map = {}
        for col in df.columns:
            c = str(col)
            if "日期" in c or c.lower() == "date":
                col_map[col] = "date"
            elif "净资产收益率" in c and "摊薄" not in c and "roe" not in col_map.values():
                col_map[col] = "roe"
            elif "毛利率" in c:
                col_map[col] = "gross_profit_margin"
            elif ("营业收入同" in c or "营收同" in c) and "revenue_yoy" not in col_map.values():
                col_map[col] = "revenue_yoy"
            elif "净利润同" in c and "扣" not in c and "net_profit_yoy" not in col_map.values():
                col_map[col] = "net_profit_yoy"
        df = df.rename(columns=col_map)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df
    except Exception as e:
        print(f"获取 {symbol} 财务指标失败: {e}")
        return pd.DataFrame()

# ===== Industry Classification =====
_industry_cache = None

def get_industry_mapping(symbols=None):
    """获取股票行业分类映射

    ★ 用于行业中性化、行业轮动因子
    ★ 首次调用会加载全部行业映射（约需30-60秒），后续调用使用缓存

    参数:
        symbols: 股票代码列表（可选）。如未提供，返回全部A股映射。

    返回: dict[str, str]，如 {"000001": "银行", "000002": "房地产", ...}

    示例:
        codes = get_index_constituents("000300")
        industries = get_industry_mapping(codes)
        # {"000001": "银行", "600000": "银行", "000002": "房地产", ...}
    """
    global _industry_cache

    if _industry_cache is None:
        _industry_cache = {}
        try:
            print("正在加载行业分类映射（首次调用，需30-60秒）...")
            boards = ak.stock_board_industry_name_em()
            total = len(boards)
            for idx, (_, board_row) in enumerate(boards.iterrows()):
                board_name = str(board_row.get("板块名称", ""))
                if not board_name:
                    continue
                try:
                    cons = ak.stock_board_industry_cons_em(symbol=board_name)
                    # Find code column
                    code_col = None
                    for col in cons.columns:
                        if "代码" in str(col) or "code" in str(col).lower():
                            code_col = col
                            break
                    if code_col is None and len(cons.columns) > 0:
                        code_col = cons.columns[0]
                    if code_col is not None:
                        for code in cons[code_col].astype(str):
                            _industry_cache[code] = board_name
                except:
                    continue
                if (idx + 1) % 20 == 0:
                    print(f"  行业映射加载中... {idx+1}/{total}")
            print(f"行业映射已加载，共 {len(_industry_cache)} 只股票")
        except Exception as e:
            print(f"加载行业映射失败: {e}")

    if symbols:
        return {s: _industry_cache.get(s, "未知") for s in symbols}
    return dict(_industry_cache)

# ===== Factor test helpers =====
def calc_ic(factor_values, forward_returns):
    """计算IC (Pearson相关系数)

    参数: 两个等长 Series (factor_values, forward_returns)
    返回: float，范围 [-1, 1]
    示例: ic = calc_ic(factor_series, return_series)
    """
    ic = factor_values.corr(forward_returns)
    return ic

def calc_rank_ic(factor_values, forward_returns):
    """计算Rank IC (Spearman相关系数)

    参数: 两个等长 Series (factor_values, forward_returns)
    返回: float，范围 [-1, 1]
    示例: ric = calc_rank_ic(factor_series, return_series)
    """
    ric, _ = stats.spearmanr(factor_values, forward_returns)
    return ric

def factor_group_test(factor_df, n_groups=5):
    """因子分组测试

    参数:
        factor_df: DataFrame，必须包含以下列：
            - date (日期)
            - symbol (股票代码)
            - factor (因子值，float)
            - forward_return (远期收益率，float)
        n_groups: 分组数量，默认5

    返回: dict，包含 group_stats/ic_mean/ic_std/icir/rank_ic_mean/rank_ic_std/rank_icir/long_short_annual 等

    示例:
        result = factor_group_test(factor_df, n_groups=5)
        print("IC均值:", result["ic_mean"])
        print("ICIR:", result["icir"])
    """
    factor_df = factor_df.dropna(subset=["factor", "forward_return"])
    if len(factor_df) == 0:
        return {"error": "No valid data after dropping NaN"}

    def assign_group(x):
        try:
            return pd.qcut(x, n_groups, labels=False, duplicates="drop")
        except:
            return pd.Series(0, index=x.index)

    factor_df["group"] = factor_df.groupby("date")["factor"].transform(
        lambda x: assign_group(x)
    )

    group_stats = factor_df.groupby("group")["forward_return"].agg(["mean", "std", "count"])
    group_stats["annualized_return"] = group_stats["mean"] * 252
    group_stats["sharpe"] = group_stats["mean"] / group_stats["std"].replace(0, np.nan) * np.sqrt(252)

    # IC series
    ic_series = factor_df.groupby("date").apply(
        lambda x: x["factor"].corr(x["forward_return"])
    )
    rank_ic_series = factor_df.groupby("date").apply(
        lambda x: stats.spearmanr(x["factor"], x["forward_return"])[0]
    )

    return {
        "group_stats": group_stats.to_dict(),
        "ic_mean": float(ic_series.mean()),
        "ic_std": float(ic_series.std()),
        "icir": float(ic_series.mean() / ic_series.std()) if ic_series.std() > 0 else 0,
        "rank_ic_mean": float(rank_ic_series.mean()),
        "rank_ic_std": float(rank_ic_series.std()),
        "rank_icir": float(rank_ic_series.mean() / rank_ic_series.std()) if rank_ic_series.std() > 0 else 0,
        "long_short_annual": float((group_stats.loc[group_stats.index.max(), "mean"] - group_stats.loc[group_stats.index.min(), "mean"]) * 252),
        "total_observations": len(factor_df),
        "date_range": f"{factor_df['date'].min()} to {factor_df['date'].max()}"
    }

# ===== Ready =====
print("数据环境已就绪，指数:", "__INDEX_NAME__", "代码:", "__INDEX_CODE__")
print("日期范围:", _start_date, "-", _end_date)
print("内置函数: get_index_constituents, get_index_data, get_stock_prices, get_batch_prices, get_valuation_data, get_batch_valuation, get_financial_indicator, get_industry_mapping, calc_ic, calc_rank_ic, factor_group_test")
print("★ 所有DataFrame列名已确定为英文，索引为DatetimeIndex，无需探索数据结构")
print("★ 行情: get_index_data(指数) / get_stock_prices(个股) / get_batch_prices(批量)")
print("★ 估值: get_valuation_data(单股) / get_batch_valuation(批量) → pe_ttm/pb/ps_ttm/dv_ratio")
print("★ 财务: get_financial_indicator(单股) → roe/毛利率/营收增速")
print("★ 行业: get_industry_mapping(代码列表) → 行业分类映射")
'''


class StockBacktestToolService(BaseToolService):
    """Factor testing tool service with market data and code execution sandbox"""

    deps = ["akshare", "scipy"]
    service_name = "因子检测"
    service_description = "A股因子有效性检测沙箱，支持沪深300/中证500等指数，提供IC/ICIR/分组测试"

    # Static tool metadata for display when deps are not installed
    TOOL_STUBS = {
        "get_market_data": {
            "description": (
                "获取A股市场数据，包括指数成分股列表和个股日线行情。"
                "支持沪深300(000300)、中证500(000905)、上证50(000016)、中证1000(000852)等指数。"
                "用于因子检测前获取数据。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "index": {"type": "string", "description": "指数代码"},
                    "start_date": {"type": "string", "description": "开始日期YYYYMMDD"},
                    "end_date": {"type": "string", "description": "结束日期YYYYMMDD"},
                    "max_stocks": {"type": "integer", "description": "最大获取股票数量"},
                },
            },
            "handler": None,
        },
        "run_backtest": {
            "description": (
                "在沙箱中执行Python因子检测代码。代码运行时已预加载akshare/pandas/numpy/scipy，"
                "并自动提供以下函数(无需import)：\n"
                "【行情数据】\n"
                "1. get_index_constituents(index_code) -> list[str] 成分股代码列表，可直接传给get_batch_prices()\n"
                "2. get_index_data(index_code, start_date, end_date) -> DataFrame 指数日线行情，★获取指数行情必须用此函数★\n"
                "   返回列: open/close/high/low/volume/turnover(float)，索引DatetimeIndex\n"
                "3. get_stock_prices(symbol, start_date, end_date) -> DataFrame 个股日线行情(仅用于个股)\n"
                "   返回列: open/close/high/low/volume/turnover/pct_change/change/turnover_rate(float)，索引DatetimeIndex\n"
                "4. get_batch_prices(symbols, start_date, end_date, max_stocks) -> dict[str,DataFrame] 批量个股行情\n"
                "【估值数据】\n"
                "5. get_valuation_data(symbol, start_date, end_date) -> DataFrame 每日估值(PE/PB/PS/股息率)\n"
                "   返回列: pe_ttm/pb/ps_ttm/dv_ratio(float)，索引DatetimeIndex\n"
                "6. get_batch_valuation(symbols, start_date, end_date, max_stocks) -> dict[str,DataFrame] 批量估值\n"
                "【财务数据】\n"
                "7. get_financial_indicator(symbol, start_year) -> DataFrame 财务指标(按报告期)\n"
                "   返回列: date/roe/gross_profit_margin/revenue_yoy/net_profit_yoy\n"
                "【行业分类】\n"
                "8. get_industry_mapping(symbols) -> dict[str,str] 行业分类映射，如{'000001':'银行'}\n"
                "【因子测试】\n"
                "9. calc_ic / calc_rank_ic -> 计算IC/Rank IC\n"
                "10. factor_group_test(factor_df, n_groups=5) -> dict 因子分组测试(需含date/symbol/factor/forward_return列)\n"
                "★ 列名和索引类型已确定，无需探索数据结构，直接使用即可。"
                "代码最后应print结果或输出JSON格式的指标。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的Python代码"},
                    "index": {"type": "string", "description": "股票池指数代码"},
                    "start_date": {"type": "string", "description": "开始日期YYYYMMDD"},
                    "end_date": {"type": "string", "description": "结束日期YYYYMMDD"},
                    "timeout": {"type": "integer", "description": "超时秒数"},
                },
            },
            "handler": None,
        },
    }

    def __init__(self, timeout: int = 60, max_output: int = 50000):
        """Initialize factor testing tool service

        Args:
            timeout: Maximum execution time in seconds
            max_output: Maximum output length in characters
        """
        self.timeout = timeout
        self.max_output = max_output

    async def get_market_data(
        self,
        index: str = "000300",
        start_date: str = "20240101",
        end_date: str = "20241231",
        max_stocks: int = 50,
    ) -> Dict[str, Any]:
        """Fetch market data for index constituents

        Args:
            index: Index code (e.g., '000300' for CSI300, '000905' for CSI500)
            start_date: Start date in YYYYMMDD format
            end_date: End date in YYYYMMDD format
            max_stocks: Maximum number of stocks to fetch (for performance)

        Returns:
            Dictionary with constituent list and price data
        """
        try:
            import akshare as ak

            index_name = INDEX_NAMES.get(index, index)

            # Get constituent stocks
            cons_df = ak.index_stock_cons(symbol=index)
            constituents = cons_df.to_dict("records") if not cons_df.empty else []

            # Limit stocks for performance
            stock_codes = [c.get("品种代码", c.get("股票代码", "")) for c in constituents[:max_stocks]]
            stock_names = [c.get("品种名称", c.get("股票名称", "")) for c in constituents[:max_stocks]]

            # Fetch price data for top stocks (with retry)
            price_data = {}
            for code, name in zip(stock_codes[:max_stocks], stock_names[:max_stocks]):
                for attempt in range(3):
                    try:
                        df = ak.stock_zh_a_hist(
                            symbol=code, period="daily",
                            start_date=start_date, end_date=end_date
                        )
                        if not df.empty:
                            price_data[code] = {
                                "name": name,
                                "rows": len(df),
                                "columns": list(df.columns),
                                "data": df.to_dict("records")[:10],  # Preview first 10 rows
                                "date_range": f"{df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}" if len(df) > 0 else ""
                            }
                        break
                    except Exception as e:
                        if attempt < 2:
                            await asyncio.sleep(1)
                        else:
                            logger.warning(f"Failed to fetch data for {code} after 3 retries: {e}")

            return {
                "index": index,
                "index_name": index_name,
                "date_range": f"{start_date} ~ {end_date}",
                "total_constituents": len(constituents),
                "fetched_stocks": len(price_data),
                "constituents_preview": [
                    {"code": c, "name": n}
                    for c, n in zip(stock_codes[:20], stock_names[:20])
                ],
                "price_data": price_data,
                "message": f"获取到{index_name}({index}) {len(constituents)}只成分股，"
                           f"已加载{len(price_data)}只股票数据"
            }

        except ImportError:
            return {"error": "akshare not installed. Run: pip install akshare"}
        except Exception as e:
            logger.error(f"Failed to get market data: {e}", exc_info=True)
            return {"error": f"获取市场数据失败: {str(e)}"}

    async def run_backtest(
        self,
        code: str,
        index: str = "000300",
        start_date: str = "20240101",
        end_date: str = "20241231",
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Execute factor testing code in a sandbox subprocess

        The code runs with preset market data helpers (get_index_constituents,
        get_stock_prices, get_batch_prices, factor_group_test, etc.)

        Args:
            code: Python code to execute
            index: Index code for stock universe (e.g., '000300' for CSI300)
            start_date: Start date in YYYYMMDD format
            end_date: End date in YYYYMMDD format
            timeout: Execution timeout in seconds

        Returns:
            Dictionary with execution results and metrics
        """
        index_name = INDEX_NAMES.get(index, index)
        effective_timeout = timeout or self.timeout

        # Build the full script: preset + user code
        # Use string replacement instead of .format() to avoid curly brace conflicts
        preset = PRESET_TEMPLATE
        preset = preset.replace("__INDEX_CODE__", index)
        preset = preset.replace("__INDEX_NAME__", f"{index_name}({index})")
        preset = preset.replace("__START_DATE__", start_date)
        preset = preset.replace("__END_DATE__", end_date)

        full_code = preset + "\n# ===== User Code =====\n" + code

        # Write to temp file and execute
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(full_code)
            script_path = f.name

        try:
            result = await self._execute_subprocess(script_path, effective_timeout)
            return result
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def _execute_subprocess(self, script_path: str, timeout: int) -> Dict[str, Any]:
        """Execute a Python script in a subprocess with timeout.

        Uses subprocess.run in a thread pool to avoid Windows ProactorEventLoop issues.

        Args:
            script_path: Path to the Python script
            timeout: Maximum execution time in seconds

        Returns:
            Dictionary with stdout, stderr, exit_code, and parsed metrics
        """
        python_exe = sys.executable
        loop = asyncio.get_event_loop()

        def _run():
            try:
                proc = subprocess.run(
                    [python_exe, script_path],
                    capture_output=True,
                    timeout=timeout,
                )
                return proc.stdout, proc.stderr, proc.returncode
            except subprocess.TimeoutExpired:
                return None, None, -1
            except Exception as e:
                return None, str(e).encode(), -2

        try:
            stdout_bytes, stderr_bytes, exit_code = await loop.run_in_executor(None, _run)

            if exit_code == -1:
                return {
                    "success": False,
                    "error": f"执行超时({timeout}秒)，代码可能包含无限循环或耗时过长",
                    "exit_code": -1,
                }

            if exit_code == -2:
                return {
                    "success": False,
                    "error": f"执行失败: {stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else '未知错误'}",
                    "exit_code": -2,
                }

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            # Truncate output if too long
            if len(stdout) > self.max_output:
                stdout = stdout[:self.max_output] + f"\n... (截断，总长度 {len(stdout)})"
            if len(stderr) > self.max_output:
                stderr = stderr[:self.max_output] + f"\n... (截断，总长度 {len(stderr)})"

            # Try to extract JSON metrics from stdout
            metrics = self._extract_metrics(stdout)

            result = {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            }

            if metrics:
                result["metrics"] = metrics

            if exit_code != 0 and stderr:
                result["error"] = self._summarize_error(stderr)

            return result

        except Exception as e:
            logger.error(f"Subprocess execution error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "exit_code": -1,
            }

    @staticmethod
    def _extract_metrics(stdout: str) -> Optional[Dict[str, Any]]:
        """Try to extract JSON metrics block from stdout.

        Looks for a JSON block wrapped in ===METRICS=== markers,
        or tries to parse the last JSON-like output.
        """
        # Strategy 1: Look for ===METRICS=== markers
        marker_start = "===METRICS==="
        marker_end = "===/METRICS==="
        start_idx = stdout.find(marker_start)
        if start_idx != -1:
            end_idx = stdout.find(marker_end, start_idx)
            if end_idx != -1:
                json_str = stdout[start_idx + len(marker_start):end_idx].strip()
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

        # Strategy 2: Try to find a JSON dict printed at the end
        # Look for the last line that starts with { and ends with }
        lines = stdout.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    result = json.loads(line)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    continue

        return None

    @staticmethod
    def _summarize_error(stderr: str) -> str:
        """Extract the most relevant error message from stderr."""
        lines = stderr.strip().split("\n")
        # Find the last traceback line that's not a framework line
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("During") and not stripped.startswith("The above"):
                if "Error" in stripped or "Exception" in stripped:
                    return stripped
        return lines[-1] if lines else "Unknown error"

    def get_tools(self) -> Dict[str, MCPTool]:
        """Get available factor testing tools"""
        return {
            "get_market_data": MCPTool(
                name="get_market_data",
                description=(
                    "获取A股市场数据，包括指数成分股列表和个股日线行情。"
                    "支持沪深300(000300)、中证500(000905)、上证50(000016)、中证1000(000852)等指数。"
                    "Use this to fetch constituent stocks and price data before factor testing."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "string",
                            "description": "指数代码: 沪深300='000300', 中证500='000905', 上证50='000016', 中证1000='000852'",
                            "default": "000300"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "开始日期，格式YYYYMMDD",
                            "default": "20240101"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "结束日期，格式YYYYMMDD",
                            "default": "20241231"
                        },
                        "max_stocks": {
                            "type": "integer",
                            "description": "最大获取股票数量（控制性能）",
                            "default": 50
                        }
                    },
                    "required": []
                },
                handler=self.get_market_data
            ),
            "run_backtest": MCPTool(
                name="run_backtest",
                description=(
                    "在沙箱中执行Python因子检测代码。代码运行时已预加载akshare/pandas/numpy/scipy，"
                    "并自动提供以下函数(无需import)：\n"
                    "【行情数据】\n"
                    "1. get_index_constituents(index_code) -> list[str] 成分股代码列表，可直接传给get_batch_prices()\n"
                    "2. get_index_data(index_code, start_date, end_date) -> DataFrame 指数日线行情，★获取指数行情必须用此函数★\n"
                    "   返回列: open/close/high/low/volume/turnover(float)，索引DatetimeIndex\n"
                    "3. get_stock_prices(symbol, start_date, end_date) -> DataFrame 个股日线行情(仅用于个股)\n"
                    "   返回列: open/close/high/low/volume/turnover/pct_change/change/turnover_rate(float)，索引DatetimeIndex\n"
                    "4. get_batch_prices(symbols, start_date, end_date, max_stocks) -> dict[str,DataFrame] 批量个股行情\n"
                    "【估值数据】\n"
                    "5. get_valuation_data(symbol, start_date, end_date) -> DataFrame 每日估值(PE/PB/PS/股息率)\n"
                    "   返回列: pe_ttm/pb/ps_ttm/dv_ratio(float)，索引DatetimeIndex\n"
                    "6. get_batch_valuation(symbols, start_date, end_date, max_stocks) -> dict[str,DataFrame] 批量估值\n"
                    "【财务数据】\n"
                    "7. get_financial_indicator(symbol, start_year) -> DataFrame 财务指标(按报告期)\n"
                    "   返回列: date/roe/gross_profit_margin/revenue_yoy/net_profit_yoy\n"
                    "【行业分类】\n"
                    "8. get_industry_mapping(symbols) -> dict[str,str] 行业分类映射，如{'000001':'银行'}\n"
                    "【因子测试】\n"
                    "9. calc_ic / calc_rank_ic -> 计算IC/Rank IC\n"
                    "10. factor_group_test(factor_df, n_groups=5) -> dict 因子分组测试(需含date/symbol/factor/forward_return列)\n"
                    "★ 列名和索引类型已确定，无需探索数据结构，直接使用即可。"
                    "代码最后应print结果或输出JSON格式的指标。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "要执行的Python代码（因子计算、有效性检测等）"
                        },
                        "index": {
                            "type": "string",
                            "description": "股票池指数代码: 沪深300='000300', 中证500='000905', 上证50='000016'",
                            "default": "000300"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "检测开始日期，格式YYYYMMDD",
                            "default": "20240101"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "检测结束日期，格式YYYYMMDD",
                            "default": "20241231"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "执行超时时间（秒）",
                            "default": 60
                        }
                    },
                    "required": ["code"]
                },
                handler=self.run_backtest
            )
        }
