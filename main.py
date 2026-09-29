import os
import time
import requests
import json
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from google import genai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_URL = os.environ.get("FIREBASE_URL")

CUSTOM_STOCK_CORRECTIONS = {
    "삼성전자": ("005930", "삼성전자", "KR"),
    "삼성전자우": ("005935", "삼성전자우", "KR"),
    "카카오": ("035720", "카카오", "KR"),
    "네이버": ("035420", "NAVER", "KR"),
    "naver": ("035420", "NAVER", "KR"),
    "sk하이닉스": ("000660", "SK하이닉스", "KR"),
    "하이닉스": ("000660", "SK하이닉스", "KR"),
    "현대차": ("005380", "현대차", "KR"),
    "앤비디아": ("NVDA", "엔비디아", "US"),
    "엔비디아": ("NVDA", "엔비디아", "US"),
    "마소": ("MSFT", "마이크로소프트", "US"),
    "마이크로소프트": ("MSFT", "마이크로소프트", "US"),
    "테슬라": ("TSLA", "테슬라", "US"),
    "애플": ("AAPL", "애플", "US"),
    "구글": ("GOOGL", "구글", "US"),
    "아마존": ("AMZN", "아마존", "US"),
}

def get_usd_exchange_rate():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            rate = data['chart']['result'][0]['meta']['regularMarketPrice']
            if rate and rate > 500:
                return float(rate)
    except Exception:
        pass
    return 1350.0

def fetch_us_stock_price(ticker: str, display_title: str):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            result = data['chart']['result'][0]
            price_usd = float(result['meta']['regularMarketPrice'])
            exchange_rate = get_usd_exchange_rate()
            price_krw = price_usd * exchange_rate
            final_name = f"{display_title} ({ticker})" if display_title != ticker else ticker

            # 배당금 정보 가져오기 (Yahoo Quote API)
            div_rate = 0.0
            try:
                q_url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
                q_res = requests.get(q_url, headers=HEADERS, timeout=2).json()
                div_rate = q_res['quoteResponse']['result'][0].get('trailingAnnualDividendRate', 0.0)
            except:
                pass

            return {
                "price": float(price_krw),
                "price_usd": price_usd,
                "name": final_name,
                "ticker": ticker,
                "is_us": True,
                "currency": "USD",
                "exchange_rate": exchange_rate,
                "dividend_rate": div_rate # 추가됨 (USD 기준 1주당 연간 배당금)
            }
    except Exception as e:
        pass
    return {"error": f"'{ticker}' 해외 시세를 불러오지 못했습니다."}

def fetch_kr_stock_price(code: str, name: str):
    try:
        url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data.get("datas") and len(data["datas"]) > 0:
                stock_data = data["datas"][0]
                price = float(str(stock_data["closePrice"]).replace(",", ""))
                
                # 배당금 정보 가져오기 (Yahoo Quote API 활용)
                div_rate = 0.0
                try:
                    q_url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={code}.KS"
                    q_res = requests.get(q_url, headers=HEADERS, timeout=2).json()
                    res_list = q_res.get('quoteResponse', {}).get('result', [])
                    if not res_list:
                        q_url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={code}.KQ"
                        q_res = requests.get(q_url, headers=HEADERS, timeout=2).json()
                        res_list = q_res.get('quoteResponse', {}).get('result', [])
                    if res_list:
                        div_rate = res_list[0].get('trailingAnnualDividendRate', 0.0)
                except:
                    pass

                return {
                    "price": price,
                    "name": stock_data.get("stockName") or name,
                    "code": code,
                    "ticker": code,
                    "is_us": False,
                    "currency": "KRW",
                    "dividend_rate": div_rate # 추가됨 (KRW 기준 1주당 연간 배당금)
                }
    except Exception as e:
        pass
    return {"error": f"'{name}' 국내 시세를 불러오지 못했습니다."}

def search_naver_finance(query: str):
    try:
        url = f"https://ac.finance.naver.com/ac?q={requests.utils.quote(query)}&q_enc=utf-8&st=111&r_lt=111"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            if items and len(items) > 0 and len(items[0]) > 0:
                for item in items[0]:
                    code = item[0][0]
                    name = item[1][0]
                    if code.isdigit() and len(code) == 6:
                        return {"type": "KR", "code": code, "name": name}
                    if not code.isdigit() and len(code) <= 5:
                        return {"type": "US", "ticker": code.upper(), "name": name}
    except Exception:
        pass
    return None

def search_yahoo_finance(query: str):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={requests.utils.quote(query)}"
        res = requests.get(url, headers=HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            quotes = data.get("quotes", [])
            for q in quotes:
                if q.get("quoteType") in ["EQUITY", "ETF"]:
                    return {"type": "US", "ticker": q.get("symbol"), "name": q.get("shortname") or query}
    except Exception:
        pass
    return None

@app.get("/api/price")
def get_price(name: str):
    query = name.strip()
    clean_q = query.lower().replace(" ", "")

    if clean_q in CUSTOM_STOCK_CORRECTIONS:
        code_or_ticker, display_name, market_type = CUSTOM_STOCK_CORRECTIONS[clean_q]
        if market_type == "KR":
            return fetch_kr_stock_price(code_or_ticker, display_name)
        else:
            return fetch_us_stock_price(code_or_ticker, display_name)

    if len(query) == 6 and query.isdigit():
        return fetch_kr_stock_price(query, query)

    naver_res = search_naver_finance(query)
    if naver_res:
        if naver_res["type"] == "KR":
            return fetch_kr_stock_price(naver_res["code"], naver_res["name"])
        elif naver_res["type"] == "US":
            res = fetch_us_stock_price(naver_res["ticker"], naver_res["name"])
            if "error" not in res:
                return res

    yahoo_res = search_yahoo_finance(query)
    if yahoo_res:
        res = fetch_us_stock_price(yahoo_res["ticker"], yahoo_res["name"])
        if "error" not in res:
            return res

    if query.isalpha():
        res = fetch_us_stock_price(query.upper(), query.upper())
        if "error" not in res:
            return res

    return {"error": f"'{name}'의 시세를 찾을 수 없습니다."}

@app.get("/api/analyze")
def analyze_stock_reason(stock_name: str):
    if not GEMINI_API_KEY:
        return {"reason": "⚠️ Gemini API 키가 설정되지 않았습니다."}

    prompt = f"주식 종목 '{stock_name}'의 최근 주가 변동 원인을 한국어로 불렛포인트(•) 3줄로 명확히 요약해주세요."
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=prompt,
                )
                if response and response.text:
                    return {"reason": response.text.strip()}
            except Exception as err:
                err_str = str(err)
                if ("503" in err_str or "500" in err_str) and attempt < 2:
                    time.sleep(2)
                    continue
                if "429" in err_str or "quota" in err_str.lower():
                    return {"reason": "⏳ 무료 AI 사용량을 잠시 초과했습니다.\n약 1분 정도 기다리신 후 다시 눌러주세요."}
                raise err
    except Exception as e:
        return {"reason": "⚠️ AI 서버가 일시적으로 응답하지 않습니다.\n잠시 후 다시 시도해주세요."}

# 👇 추가됨: 포트폴리오 전체 AI 모닝 브리핑 엔진
@app.post("/api/analyze_portfolio")
async def analyze_portfolio(request: Request):
    if not GEMINI_API_KEY:
        return {"reason": "⚠️ Gemini API 키가 설정되지 않았습니다."}
    
    data = await request.json()
    portfolio_text = data.get("text", "")
    
    prompt = f"다음은 내 주식 포트폴리오 현황이야.\n{portfolio_text}\n이 포트폴리오의 전반적인 상태(수익/손실)와 관련된 최근 글로벌 증시(미국/한국) 시장 동향을 바탕으로, '오늘의 모닝 브리핑'을 3~4줄로 펀드매니저처럼 멋지게 요약해줘."
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=prompt,
                )
                if response and response.text:
                    return {"reason": response.text.strip()}
            except Exception as err:
                err_str = str(err)
                if ("503" in err_str or "500" in err_str) and attempt < 2:
                    time.sleep(2)
                    continue
                if "429" in err_str or "quota" in err_str.lower():
                    return {"reason": "⏳ 무료 AI 사용량을 잠시 초과했습니다. 잠시 후 다시 눌러주세요."}
                raise err
    except Exception as e:
        return {"reason": "⚠️ AI 서버가 일시적으로 응답하지 않습니다."}

@app.get("/api/portfolio")
def get_portfolio():
    if not FIREBASE_URL:
        return []
    try:
        res = requests.get(f"{FIREBASE_URL}/portfolio.json", timeout=3)
        if res.status_code == 200:
            data = res.json()
            return data if data else []
    except:
        pass
    return []

@app.post("/api/portfolio")
async def save_portfolio(request: Request):
    if not FIREBASE_URL:
        return {"error": "DB URL이 설정되지 않았습니다."}
    
    data = await request.json()
    try:
        requests.put(f"{FIREBASE_URL}/portfolio.json", json=data, timeout=3)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/manifest.json")
def get_manifest():
    return {
        "name": "CYBER PORTFOLIO",
        "short_name": "PORTFOLIO",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1e1b4b",
        "theme_color": "#1e1b4b",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/7376/7376517.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }

@app.get("/sw.js")
def get_sw():
    js_code = "self.addEventListener('fetch', function(event) {});"
    return Response(content=js_code, media_type="application/javascript")

@app.get("/")
def serve_frontend():
    return FileResponse("index3.html")
