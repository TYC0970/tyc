import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import ta
import requests
import time
import akshare as ak
from supabase import create_client

# ========== 页面配置 ==========
st.set_page_config(
    page_title="AI短线助手 · 免费版",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== 暗色主题 CSS ==========
st.markdown("""
<style>
    /* 全局深色背景 */
    .stApp {
        background-color: #0a0c10;
    }
    /* 卡片、容器背景 */
    .css-1aumxhk, .element-container, .stMarkdown, .stDataFrame, .stForm, .stExpander {
        background-color: #1e1f24;
        border-radius: 20px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        border: 1px solid #2c2e33;
        color: #e5e9f0;
    }
    /* 侧边栏深色背景 */
    .css-1d391kg {
        background-color: #141517;
        border-right: 1px solid #2c2e33;
    }
    /* 标题 */
    h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        color: #c084fc;
        font-weight: 600;
        letter-spacing: -0.01em;
    }
    /* 按钮 */
    .stButton > button {
        background: linear-gradient(135deg, #a855f7, #7c3aed);
        color: white;
        border-radius: 40px;
        border: none;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 0 8px rgba(168,85,247,0.5);
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 0 15px rgba(168,85,247,0.8);
        background: linear-gradient(135deg, #c084fc, #a855f7);
    }
    /* 输入框 */
    .stTextInput > div > div > input {
        background-color: #2c2e33;
        border: 1px solid #3f4147;
        border-radius: 12px;
        color: #f0f0f0;
        padding: 0.5rem 1rem;
    }
    .stNumberInput > div > div > input {
        background-color: #2c2e33;
        border: 1px solid #3f4147;
        border-radius: 12px;
        color: #f0f0f0;
    }
    /* 指标卡片 */
    .metric-card {
        background: linear-gradient(135deg, #2d2f36, #1e1f24);
        border-radius: 20px;
        padding: 1.2rem;
        color: white;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        border: 1px solid #3f4147;
    }
    .metric-card .label {
        font-size: 0.9rem;
        opacity: 0.8;
        color: #cbd5e1;
    }
    .metric-card .value {
        font-size: 2rem;
        font-weight: bold;
        margin-top: 0.5rem;
        color: #c084fc;
    }
    /* 标签页 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #1e1f24;
        border-radius: 12px;
        padding: 0.2rem;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 12px;
        padding: 0.5rem 1rem;
        color: #a0a0a0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2d2f36;
        color: #c084fc;
        font-weight: 600;
    }
    .footer {
        text-align: center;
        font-size: 0.8rem;
        color: #6b7280;
        margin-top: 2rem;
        padding: 1rem;
        border-top: 1px solid #2c2e33;
    }
</style>
""", unsafe_allow_html=True)

# ========== Supabase 初始化 ==========
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except:
    st.error("请先配置 Supabase Secrets（SUPABASE_URL 和 SUPABASE_KEY）")
    st.stop()

# ========== 用户认证 ==========
def login():
    st.sidebar.title("🔐 登录")
    email = st.sidebar.text_input("邮箱")
    pwd = st.sidebar.text_input("密码", type="password")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("登录"):
            try:
                supabase.auth.sign_in_with_password({"email": email, "password": pwd})
                st.session_state.user = email
                st.experimental_rerun()
            except:
                st.sidebar.error("登录失败")
    with col2:
        if st.button("注册"):
            try:
                supabase.auth.sign_up({"email": email, "password": pwd})
                st.sidebar.success("注册成功，请登录")
            except:
                Exception as e:
                st.sidebar.error(f"注册失败: {e}")

if "user" not in st.session_state:
    login()
    st.stop()

user = st.session_state.user

# ========== 初始化会话状态 ==========
if "watchlist" not in st.session_state:
    st.session_state.watchlist = {}
if "weights" not in st.session_state:
    st.session_state.weights = {"w_macd": 2.0, "w_kdj": 2.0, "w_rsi": 1.0, "w_vol": 1.0}

# ========== 东方财富数据接口 ==========
def format_code(code):
    """将6位数字代码转为带后缀格式（仅用于内部，实际接口需要纯数字）"""
    return code.strip()

def fetch_quote(symbol, api_key=None):
    """通过东方财富接口获取实时行情"""
    try:
        # 提取纯数字代码
        code = symbol.split('.')[0] if '.' in symbol else symbol
        # 判断市场：深市 0，沪市 1
        if code.startswith(('00', '30')):
            secid = f"0.{code}"
        else:
            secid = f"1.{code}"
        
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'secid': secid,
            'fields': 'f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58,f60,f84,f85,f86,f87,f92,f93,f94,f95,f96,f97,f98,f99,f100,f101,f102,f103,f104,f105,f106,f107,f108,f109,f110,f111,f112,f113,f114,f115,f116,f117,f118,f119,f120,f121,f122,f123,f124,f125,f126,f127,f128,f129,f130,f131,f132,f133,f134,f135,f136,f137,f138,f139,f140,f141,f142,f143,f144,f145,f146,f147',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b'
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if data['data'] is None:
            return None
        
        d = data['data']
        name = d.get('f58', '')
        latest = d.get('f43', 0) / 100
        change_pct = d.get('f170', 0) / 100
        volume = d.get('f47', 0)
        amount = d.get('f45', 0)
        
        return {
            'name': name,
            'last_price': latest,
            'change_pct': change_pct,
            'volume': volume,
            'amount': amount,
            'open': d.get('f46', 0) / 100,
            'high': d.get('f44', 0) / 100,
            'low': d.get('f45', 0) / 100,
            'pre_close': d.get('f60', 0) / 100
        }
    except Exception as e:
        print(f"获取行情失败: {e}")
        return None

def fetch_kline(symbol, api_key=None, period="1d", count=60):
    """通过东方财富接口获取历史K线"""
    try:
        code = symbol.split('.')[0] if '.' in symbol else symbol
        if code.startswith(('00', '30')):
            secid = f"0.{code}"
        else:
            secid = f"1.{code}"
        
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': 101,      # 日线
            'fqt': 1,        # 前复权
            'lmt': count,
            'end': '20500101'
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get('data') is None:
            return None
        
        klines = data['data']['klines']
        records = []
        for line in klines:
            parts = line.split(',')
            records.append({
                'date': parts[0],
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': float(parts[5])
            })
        df = pd.DataFrame(records)
        return df
    except Exception as e:
        print(f"获取K线失败: {e}")
        return None

# ========== 技术指标计算 ==========
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

# ========== 板块分析（akshare）==========
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

# ========== 侧边栏 ==========
with st.sidebar:
    st.image("https://img.icons8.com/color/48/000000/stocks.png", width=40)
    st.markdown(f"### 欢迎，{user}")
    st.markdown("---")
    
    st.subheader("⚙️ 数据源")
    st.info("✅ 东方财富（免费，无需API Key）")
    api_key = "dummy"  # 占位，实际不需要
    
    st.markdown("---")
    st.subheader("📋 自选股管理")
    add_code = st.text_input("添加股票代码（6位数字）")
    if st.button("➕ 加入自选"):
        symbol = format_code(add_code)
        quote = fetch_quote(symbol, api_key)
        if quote:
            st.session_state.watchlist[symbol] = {
                "name": quote['name'],
                "buy_price": None,
                "sell_price": None,
                "stop_price": None,
                "notes": ""
            }
            st.success(f"已添加 {symbol}")
            st.experimental_rerun()
        else:
            st.error("获取失败，请检查代码")
    
    if st.session_state.watchlist:
        st.markdown("---")
        st.markdown("#### 我的自选")
        for code, data in st.session_state.watchlist.items():
            with st.container():
                col1, col2 = st.columns([3,1])
                with col1:
                    st.markdown(f"**{data['name']}**  \n`{code}`")
                    quote = fetch_quote(code, api_key)
                    if quote:
                        current = quote['last_price']
                        change = quote.get('change_pct', 0)
                        st.caption(f"现价: {current:.2f}  ({change:+.2f}%)")
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
                st.markdown("---")
    else:
        st.info("暂无自选股，请添加")

# ========== 主界面 ==========
st.title("📈 AI短线助手 · 免费版")
st.caption("东方财富实时数据 | 技术指标 | 智能信号 | 自选管理 | 板块热点")

tab_main, tab_plate = st.tabs(["📊 股票分析", "🔥 热门板块"])

with tab_main:
    st.subheader("🔍 个股分析")
    code_input = st.text_input("输入股票代码（6位数字）", placeholder="例如 000001")
    if code_input:
        symbol = format_code(code_input)
        with st.spinner("获取实时数据..."):
            quote = fetch_quote(symbol, api_key)
            if quote:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="label">股票名称</div>
                        <div class="value">{quote['name']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="label">最新价</div>
                        <div class="value">{quote['last_price']:.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col3:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="label">涨跌幅</div>
                        <div class="value">{quote['change_pct']:+.2f}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
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
                    
                    with st.expander("📈 技术指标详情"):
                        col_a, col_b, col_c, col_d = st.columns(4)
                        col_a.metric("MACD", f"{indicators['macd']:.2f}", f"{indicators['macd_signal']:.2f}")
                        col_b.metric("KDJ K值", f"{indicators['stoch_k']:.2f}")
                        col_c.metric("RSI", f"{indicators['rsi']:.2f}")
                        col_d.metric("成交量比", f"{indicators['volume_ratio']:.2f}")
                else:
                    st.warning("K线数据不足，无法计算指标")
            else:
                st.error("获取失败，请检查股票代码")
    
    # 记录交易
    st.subheader("✍️ 记录交易")
    with st.form("trade_form"):
        trade_code = st.text_input("股票代码")
        buy_price = st.number_input("买入价", step=0.01)
        sell_price = st.number_input("卖出价", step=0.01)
        submitted = st.form_submit_button("保存交易")
        if submitted:
            return_pct = (sell_price - buy_price) / buy_price * 100
            if return_pct > 0:
                st.session_state.weights = {k: v + 0.01 for k, v in st.session_state.weights.items()}
            else:
                st.session_state.weights = {k: v - 0.01 for k, v in st.session_state.weights.items()}
            for k in st.session_state.weights:
                st.session_state.weights[k] = max(0.5, min(5.0, st.session_state.weights[k]))
            st.success(f"交易已记录，盈亏: {return_pct:.2f}%，AI权重已更新")
    st.write("当前AI学习权重：", st.session_state.weights)

with tab_plate:
    st.subheader("🔥 热门板块分析（行业板块）")
    with st.spinner("正在获取板块数据..."):
        today, yesterday, tomorrow = get_top_plates(limit=10)
    if today:
        tab1, tab2, tab3 = st.tabs(["今日热门", "昨日热门", "明日预测"])
        with tab1:
            for i, (code, name, score) in enumerate(today, 1):
                with st.expander(f"{i}. {name}  (评分 {score:.1f})"):
                    stocks = get_plate_stocks(code)
                    if stocks:
                        st.write("龙头股（按成交额）：")
                        for s in stocks:
                            st.write(f"  {s['名称']}({s['代码']}) {s['最新价']} {s['涨跌幅']:.2f}%")
        with tab2:
            for i, (code, name, score) in enumerate(yesterday, 1):
                st.write(f"{i}. {name}  (评分 {score:.1f})")
        with tab3:
            for i, (code, name, score) in enumerate(tomorrow, 1):
                st.write(f"{i}. {name}  (预测评分 {score:.1f})")
    else:
        st.warning("无法获取板块数据")

# ========== 页脚 ==========
st.markdown("""
<div class="footer">
    📊 数据来源：东方财富 & akshare | 技术指标基于 TA-Lib | 风险提示：仅供参考，不构成投资建议
</div>
""", unsafe_allow_html=True)
