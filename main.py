import os
import json
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import anthropic

load_dotenv()

app = FastAPI()

class AnalyzeRequest(BaseModel):
    url: str
    api_key: Optional[str] = None

class SaveKeyRequest(BaseModel):
    api_key: str

@app.post("/api/save-key")
async def save_key(req: SaveKeyRequest):
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    key_found = False
    for i, line in enumerate(lines):
        if line.startswith("ANTHROPIC_API_KEY="):
            lines[i] = f"ANTHROPIC_API_KEY={req.api_key}\n"
            key_found = True
            break
    if not key_found:
        lines.append(f"ANTHROPIC_API_KEY={req.api_key}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    load_dotenv(override=True)
    return {"status": "saved"}

@app.get("/api/check-key")
async def check_key():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return {"has_key": bool(key), "key_preview": key[:8] + "..." if key else ""}

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    api_key = req.api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="APIキーが設定されていません")
    async def generate():
        try:
            from scraper import scrape_reviews
            yield f"data: {json.dumps({'type': 'status', 'message': 'URLを解析中...'})}\n\n"
            await asyncio.sleep(0.1)
            async for event in scrape_reviews(req.url):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0.01)
                if event.get("type") == "reviews_complete":
                    reviews = event.get("reviews", [])
                    total = event.get("total", len(reviews))
                    yield f"data: {json.dumps({'type': 'status', 'message': f'全{total}件のレビューを取得完了。AI分析を開始します...'})}\n\n"
                    await asyncio.sleep(0.1)
                    async for analysis_event in analyze_reviews(reviews, api_key):
                        yield f"data: {json.dumps(analysis_event)}\n\n"
                        await asyncio.sleep(0.01)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

async def analyze_reviews(reviews: list, api_key: str):
    if not reviews:
        yield {"type": "error", "message": "レビューが取得できませんでした"}
        return
    yield {"type": "status", "message": "分析中... (星評価を集計しています)"}
    star_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in reviews:
        rating = r.get("rating", 0)
        if 1 <= rating <= 5:
            star_counts[rating] += 1
    yield {"type": "status", "message": "分析中... (AIがレビューを読み込んでいます)"}
    sample = reviews[:500]
    review_texts = []
    for i, r in enumerate(sample):
        text = r.get("text", "").strip()
        rating = r.get("rating", "?")
        if text:
            review_texts.append(f"[{rating}★] {text}")
    combined = "\n---\n".join(review_texts)
    total_count = len(reviews)
    prompt = f"""以下は商品の全{total_count}件中{len(review_texts)}件のレビューです（サンプリング）。\n\n{combined}\n\n以下の形式でJSONのみを返してください（コードブロック不要）：\n{{\n  "good_points": ["良い点1", "良い点2", "良い点3", "良い点4", "良い点5"],\n  "bad_points": ["悪い点1", "悪い点2", "悪い点3"],\n  "positive_ratio": 75,\n  "negative_ratio": 25,\n  "keywords": ["キーワード1", "キーワード2", "キーワード3", "キーワード4", "キーワード5", "キーワード6", "キーワード7", "キーワード8", "キーワード9", "キーワード10"],\n  "recommend_score": 4,\n  "recommend_reason": "総合的なおすすめ理由を2～3文で"\n}}"""
    yield {"type": "status", "message": "分析中... (AIが評価を生成しています)"}
    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=1000, messages=[{"role": "user", "content": prompt}])
        raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        analysis = json.loads(raw)
        yield {"type": "complete", "star_counts": star_counts, "total_reviews": total_count, "analysis": analysis}
    except json.JSONDecodeError as e:
        yield {"type": "error", "message": f"AI応答のパースに失敗: {str(e)}"}
    except Exception as e:
        yield {"type": "error", "message": f"AI分析エラー: {str(e)}"}

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()
