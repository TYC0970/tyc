import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ta
import requests
import time
import akshare as ak
from tickflow import TickFlow
from supabase import create_client

# 页面配置
st.set_page_config(page_title="专属AI短线助手", page_icon="📈", layout="wide")

# Supabase 初始化（需要 Streamlit Secrets 提供 URL 和 KEY）
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except:
    st.error("请先配置 Supabase Secrets")
    st.stop()

# 用户登录
def login():
    st.sidebar.title("🔐 登录")
    email = st.sidebar.text_input("邮箱")
    pwd = st.sidebar.text_input("密码", type="password")
    if st.sidebar.button("登录"):
        try:
            supabase.auth.sign_in_with_password({"email": email, "password": pwd})
            st.session_state.user = email
            st.experimental_rerun()
        except:
            st.sidebar.error("登录失败")
    if st.sidebar.button("注册"):
        try:
            supabase.auth.sign_up({"email": email, "password": pwd})
            st.sidebar.success("注册成功，请登录")
        except:
            st.sidebar.error("注册失败")

if "user" not in st.session_state:
    login()
    st.stop()

user = st.session_state.user

# 初始化会话状态
if "watchlist" not in st.session_state:
    st.session_state.watchlist = {}
if "weights" not in st.session_state:
    st.session_state.weights = {"w_macd": 2.0, "w_kdj": 2.0, "w_rsi": 1.0, "w_vol": 1.0}

# 辅助函数
def format_code(code):
    code = code.strip()
    if len(code) == 6:
        if code.startswith(('00', '30')):
            return f"{code}.SZ"
        elif code.startswith(('60', '68')):
            return f"{code}.SH"
    return code

def fetch_quote(symbol, api_key):
    try:
        tf = TickFlow(api_key=api_key)
        quotes = tf.quotes.get(symbols=[symbol], as_dataframe=True)
        if quotes.empty:
            return None
        return quotes.iloc[0].to_dict()
    except:
        return None

def fetch_kline(symbol, api_key, period="1d", count=60):
    try:
        tf = TickFlow(api_key=api_key)
        df = tf.klines.get(symbol, period=period, count=count, as_dataframe=True)
        if df is None or df.empty:
            return None
        df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}, inplace=True)
        return df
    except:
        return None

def compute_indicators(df):
    df = df.copy()
    macd = ta.trend.MACD(close=df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['stoch_k'] = ta.momentum.StochRSI(close=df['close']).stochrsi_k()
    df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
    df['volume_ma5'] = df['volume'].rolling(5).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma5']
    return df.iloc[-1].to_dict()

def generate_signal(indicators, weights):
    score = 0
    if indicators['macd'] > indicators['macd_signal']:
        score += 2 * weights['w_macd']
    else:
        score -= 2 * weights['w_macd']
    k = indicators['stoch_k']
    if k < 20:
        score += 2 * weights['w_kdj']
    elif k > 80:
        score -= 2 * weights['w_kdj']
    rsi = indicators['rsi']
    if rsi < 30:
        score += 1 * weights['w_rsi']
    elif rsi > 70:
        score -= 1 * weights['w_rsi']
    vol = indicators['volume_ratio']
    if vol > 1.5:
        score += 1 * weights['w_vol']
    elif vol < 0.7:
        score -= 1 * weights['w_vol']
    if score >= 2:
        return "买入", score
    elif score <= -2:
        return "卖出", score
    else:
        return "观望", score

# ---------- 板块分析 ----------
def get_industry_plates():
    try:
        plate_list = ak.stock_board_industry_name_em()
        plate_index = ak.stock_board_industry_index_em()
        df = pd.merge(plate_list, plate_index, left_on='板块名称', right_on='名称')
        return df[['板块代码', '板块名称', '最新价', '涨跌幅', '成交量', '成交额']]
    except:
        return pd.DataFrame()

def get_historical_plate_data(plate_code, days=5):
    try:
        df = ak.stock_board_industry_hist(symbol=plate_code, period="daily", adjust="")
        if df.empty:
            return None
        df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '涨跌幅': 'pct_change'}, inplace=True)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').tail(days)
        return df
    except:
        return None

def calculate_plate_score(today_row, hist_df=None):
    score = 0.0
    pct = today_row['涨跌幅']
    if pct > 3:
        score += 30
    elif pct > 1:
        score += 20
    elif pct > 0:
        score += 10
    elif pct > -1:
        score -= 5
    else:
        score -= 10
    amount = today_row['成交额'] / 1e8
    if amount > 500:
        score += 20
    elif amount > 200:
        score += 15
    elif amount > 100:
        score += 10
    else:
        score += 5
    if hist_df is not None and len(hist_df) >= 3:
        avg_pct = hist_df['pct_change'].tail(3).mean()
        if avg_pct > 2:
            score += 20
        elif avg_pct > 0.5:
            score += 10
        up_days = sum(hist_df['pct_change'].tail(3) > 0)
        score += up_days * 5
    return score

def get_top_plates(limit=10):
    today_df = get_industry_plates()
    if today_df.empty:
        return None, None, None
    today_scores = []
    yesterday_scores = []
    tomorrow_scores = []
    for _, row in today_df.iterrows():
        code = row['板块代码']
        name = row['板块名称']
        hist = get_historical_plate_data(code, days=5)
        today_score = calculate_plate_score(row, hist)
        yesterday_score = 0
        if hist is not None and len(hist) >= 2:
            yesterday_row = hist.iloc[-2]
            y_dict = {'涨跌幅': yesterday_row['pct_change'], '成交额': row['成交额']}
            yesterday_score = calculate_plate_score(y_dict, hist.iloc[:-1])
        else:
            yesterday_score = today_score * 0.7
        tomorrow_score = today_score * 0.8 + yesterday_score * 0.2
        today_scores.append((code, name, today_score))
        yesterday_scores.append((code, name, yesterday_score))
        tomorrow_scores.append((code, name, tomorrow_score))
        time.sleep(0.1)
    today_scores.sort(key=lambda x: x[2], reverse=True)
    yesterday_scores.sort(key=lambda x: x[2], reverse=True)
    tomorrow_scores.sort(key=lambda x: x[2], reverse=True)
    return today_scores[:limit], yesterday_scores[:limit], tomorrow_scores[:limit]

def get_plate_stocks(plate_code, top_n=10):
    try:
        cons = ak.stock_board_industry_cons_em(symbol=plate_code)
        if cons.empty:
            return []
        spot = ak.stock_zh_a_spot()
        merged = pd.merge(cons, spot, left_on='代码', right_on='代码')
        merged = merged.sort_values('成交额', ascending=False).head(top_n)
        return merged[['代码', '名称', '最新价', '涨跌幅']].to_dict('records')
    except:
        return []

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("⚙️ 设置")
    api_key = st.text_input("TickFlow API Key", type="password")
    if not api_key:
        st.warning("请填入TickFlow API Key")
    st.markdown("---")
    st.subheader("📋 自选股")
    add_code = st.text_input("添加股票代码")
    if st.button("加入自选") and api_key:
        symbol = format_code(add_code)
        quote = fetch_quote(symbol, api_key)
        if quote:
            st.session_state.watchlist[symbol] = {
                "name": quote.get('name', symbol),
                "buy_price": None,
                "sell_price": None,
                "stop_price": None,
                "notes": ""
            }
            st.success(f"已添加 {symbol}")
            st.experimental_rerun()
        else:
            st.error("获取失败")
    for code, data in st.session_state.watchlist.items():
        with st.container():
            col1, col2 = st.columns([3,1])
            with col1:
                st.markdown(f"**{data['name']} ({code})**")
                if api_key:
                    quote = fetch_quote(code, api_key)
                    if quote:
                        current = quote['last_price']
                        change = quote.get('change_pct', 0)
                        st.caption(f"现价: {current:.2f} ({change:+.2f}%)")
                buy_price = st.number_input("计划买入价", value=data.get('buy_price', 0.0), step=0.01, key=f"buy_{code}")
                sell_price = st.number_input("计划卖出价", value=data.get('sell_price', 0.0), step=0.01, key=f"sell_{code}")
                stop_price = st.number_input("止损价", value=data.get('stop_price', 0.0), step=0.01, key=f"stop_{code}")
                if (buy_price, sell_price, stop_price) != (data.get('buy_price'), data.get('sell_price'), data.get('stop_price')):
                    data['buy_price'] = buy_price
                    data['sell_price'] = sell_price
                    data['stop_price'] = stop_price
                if buy_price and buy_price > 0 and quote:
                    if sell_price and sell_price > 0:
                        profit_pct = (sell_price - buy_price) / buy_price * 100
                        st.info(f"📊 预期盈利: {profit_pct:+.2f}%")
                    if stop_price and stop_price > 0 and current <= stop_price:
                        st.error("⚠️ 触及止损线！")
            with col2:
                if st.button("删除", key=f"del_{code}"):
                    del st.session_state.watchlist[code]
                    st.experimental_rerun()

# ---------- 主界面 ----------
st.title("📈 专属AI短线助手")
st.caption(f"欢迎 {user}！AI会从您的交易中学习，不断优化信号")

tab_main, tab_plate = st.tabs(["📊 股票分析", "🔥 热门板块"])

with tab_main:
    st.subheader("🔍 股票分析")
    code_input = st.text_input("输入股票代码", placeholder="000001")
    if code_input and api_key:
        symbol = format_code(code_input)
        with st.spinner("获取实时数据..."):
            quote = fetch_quote(symbol, api_key)
            if quote:
                col1, col2, col3 = st.columns(3)
                col1.metric("名称", quote['name'])
                col2.metric("最新价", f"{quote['last_price']:.2f}")
                col3.metric("涨跌幅", f"{quote.get('change_pct', 0):+.2f}%")
                df = fetch_kline(symbol, api_key, period="1d", count=60)
                if df is not None and len(df) >= 30:
                    indicators = compute_indicators(df)
                    signal, score = generate_signal(indicators, st.session_state.weights)
                    st.subheader("🎯 AI推荐信号")
                    if signal == "买入":
                        st.success(f"**买入** (加权评分 {score:.2f})")
                    elif signal == "卖出":
                        st.error(f"**卖出** (加权评分 {score:.2f})")
                    else:
                        st.info(f"**观望** (加权评分 {score:.2f})")
                    with st.expander("指标详情"):
                        st.write(f"MACD: {indicators['macd']:.2f} | 信号线: {indicators['macd_signal']:.2f}")
                        st.write(f"KDJ K值: {indicators['stoch_k']:.2f}")
                        st.write(f"RSI: {indicators['rsi']:.2f}")
                        st.write(f"成交量比: {indicators['volume_ratio']:.2f}")
                else:
                    st.warning("K线数据不足")
            else:
                st.error("获取失败")

    # 记录交易
    st.subheader("✍️ 记录交易")
    with st.form("trade_form"):
        trade_code = st.text_input("股票代码")
        buy_price = st.number_input("买入价", step=0.01)
        sell_price = st.number_input("卖出价", step=0.01)
        submitted = st.form_submit_button("保存交易")
        if submitted:
            return_pct = (sell_price - buy_price) / buy_price * 100
            # 简化学习：根据盈亏调整权重
            if return_pct > 0:
                st.session_state.weights = {k: v + 0.01 for k, v in st.session_state.weights.items()}
            else:
                st.session_state.weights = {k: v - 0.01 for k, v in st.session_state.weights.items()}
            for k in st.session_state.weights:
                st.session_state.weights[k] = max(0.5, min(5.0, st.session_state.weights[k]))
            st.success(f"交易已记录，盈亏: {return_pct:.2f}%，AI权重已更新")
    st.write("当前AI权重：", st.session_state.weights)

with tab_plate:
    st.subheader("🔥 热门板块分析（行业板块）")
    with st.spinner("正在获取板块数据..."):
        today, yesterday, tomorrow = get_top_plates(limit=10)
    if today:
        tab1, tab2, tab3 = st.tabs(["今日热门", "昨日热门", "明日预测"])
        with tab1:
            for i, (code, name, score) in enumerate(today, 1):
                with st.expander(f"{i}. {name} (评分 {score:.1f})"):
                    stocks = get_plate_stocks(code)
                    if stocks:
                        st.write("龙头股（按成交额）：")
                        for s in stocks:
                            st.write(f"  {s['名称']}({s['代码']}) {s['最新价']} {s['涨跌幅']:.2f}%")
        with tab2:
            for i, (code, name, score) in enumerate(yesterday, 1):
                st.write(f"{i}. {name} (评分 {score:.1f})")
        with tab3:
            for i, (code, name, score) in enumerate(tomorrow, 1):
                st.write(f"{i}. {name} (预测评分 {score:.1f})")
    else:
        st.warning("无法获取板块数据")
