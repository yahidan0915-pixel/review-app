import asyncio
import re
from typing import AsyncGenerator
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


async def scrape_reviews(url: str) -> AsyncGenerator[dict, None]:
    if "amazon.co.jp" in url or "amazon.com" in url:
        async for event in scrape_amazon(url):
            yield event
    elif "rakuten.co.jp" in url:
        async for event in scrape_rakuten(url):
            yield event
    else:
        yield {"type": "error", "message": "対応していないURLです。Amazon.co.jpまたは楽天市場のURLを入力してください。"}


async def scrape_amazon(url: str) -> AsyncGenerator[dict, None]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9"}
        )
        page = await context.new_page()
        try:
            yield {"type": "status", "message": "商品ページを読み込んでいます..."}
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            asin = extract_asin(url)
            if not asin:
                asin = await page.evaluate("""
                    () => {
                        const el = document.querySelector('[data-asin]');
                        return el ? el.getAttribute('data-asin') : null;
                    }
                """)
            if not asin:
                yield {"type": "error", "message": "商品ASINが取得できませんでした"}
                return
            yield {"type": "status", "message": "総レビュー件数を確認しています..."}
            review_url = f"https://www.amazon.co.jp/product-reviews/{asin}?pageNumber=1&reviewerType=all_reviews"
            await page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            total_reviews = await get_amazon_total_reviews(page)
            if total_reviews == 0:
                yield {"type": "error", "message": "レビューが見つかりませんでした"}
                return
            total_pages = (total_reviews + 9) // 10
            yield {"type": "total", "total": total_reviews, "pages": total_pages}
            yield {"type": "status", "message": f"総レビュー数: {total_reviews}件 ({total_pages}ページ)"}
            all_reviews = []
            for page_num in range(1, total_pages + 1):
                retries = 0
                while retries < 3:
                    try:
                        if page_num > 1:
                            review_url = f"https://www.amazon.co.jp/product-reviews/{asin}?pageNumber={page_num}&reviewerType=all_reviews"
                            await page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(1.5)
                        reviews = await extract_amazon_reviews(page)
                        all_reviews.extend(reviews)
                        yield {"type": "progress", "fetched": len(all_reviews), "total": total_reviews, "page": page_num, "total_pages": total_pages}
                        break
                    except PlaywrightTimeout:
                        retries += 1
                        if retries < 3:
                            yield {"type": "status", "message": f"ページ {page_num} の取得に失敗。リトライ {retries}/3..."}
                            await asyncio.sleep(3)
                        else:
                            yield {"type": "status", "message": f"ページ {page_num} をスキップと3回失敗）"}
                    except Exception as e:
                        retries += 1
                        if retries >= 3:
                            yield {"type": "status", "message": f"ページ {page_num} をスキップ: {str(e)[:50]}"}
                            break
                        await asyncio.sleep(2)
            yield {"type": "reviews_complete", "reviews": all_reviews, "total": total_reviews}
        except Exception as e:
            yield {"type": "error", "message": f"スクレイピング中にエラーが発生しました: {str(e)}"}
        finally:
            await browser.close()


def extract_asin(url: str) -> str:
    patterns = [r"/dp/([A-Z0-9]{10})", r"/gp/product/([A-Z0-9]{10})", r"ASIN=([A-Z0-9]{10})"]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


async def get_amazon_total_reviews(page) -> int:
    selectors = ["[data-hook='total-review-count']", "#filter-info-section span"]
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                text = await el.inner_text()
                nums = re.findall(r"[\d,]+", text.replace(",", ""))
                if nums:
                    return int(nums[0].replace(",", ""))
        except:
            continue
    try:
        content = await page.content()
        match = re.search(r"([\d,]+)\s*件のグローバル評価", content)
        if match:
            return int(match.group(1).replace(",", ""))
        match = re.search(r"([\d,]+)\s*global ratings", content)
        if match:
            return int(match.group(1).replace(",", ""))
    except:
        pass
    reviews = await extract_amazon_reviews(page)
    return len(reviews) if reviews else 0


async def extract_amazon_reviews(page) -> list:
    reviews = []
    try:
        review_elements = await page.query_selector_all("[data-hook='review']")
        for el in review_elements:
            try:
                rating_el = await el.query_selector("[data-hook='review-star-rating'] .a-icon-alt, [data-hook='cmps-review-star-rating'] .a-icon-alt")
                rating = 0
                if rating_el:
                    rating_text = await rating_el.inner_text()
                    match = re.search(r"(\d+\.?\d*)", rating_text)
                    if match:
                        rating = round(float(match.group(1)))
                text_el = await el.query_selector("[data-hook='review-body'] span")
                text = ""
                if text_el:
                    text = (await text_el.inner_text()).strip()
                if text:
                    reviews.append({"rating": rating, "text": text})
            except:
                continue
    except:
        pass
    return reviews


async def scrape_rakuten(url: str) -> AsyncGenerator[dict, None]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
            extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9"}
        )
        page = await context.new_page()
        try:
            yield {"type": "status", "message": "楽天商品ページを読み込んでいます..."}
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            review_base_url = await get_rakuten_review_url(page, url)
            if not review_base_url:
                yield {"type": "error", "message": "楽天レビューページのURLが取得できませんでした"}
                return
            yield {"type": "status", "message": "総レビュー件数を確認しています..."}
            await page.goto(review_base_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            total_reviews = await get_rakuten_total_reviews(page)
            if total_reviews == 0:
                yield {"type": "error", "message": "レビューが見つかりませんでした"}
                return
            total_pages = (total_reviews + 29) // 30
            yield {"type": "total", "total": total_reviews, "pages": total_pages}
            yield {"type": "status", "message": f"総レビュー数: {total_reviews}件 ({total_pages}ページ)"}
            all_reviews = []
            for page_num in range(1, total_pages + 1):
                retries = 0
                while retries < 3:
                    try:
                        page_url = f"{review_base_url}?p={page_num}" if page_num > 1 else review_base_url
                        if page_num > 1:
                            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(1.5)
                        reviews = await extract_rakuten_reviews(page)
                        all_reviews.extend(reviews)
                        yield {"type": "progress", "fetched": len(all_reviews), "total": total_reviews, "page": page_num, "total_pages": total_pages}
                        break
                    except PlaywrightTimeout:
                        retries += 1
                        if retries < 3:
                            yield {"type": "status", "message": f"ページ {page_num} のリトライ {retries}/3..."}
                            await asyncio.sleep(3)
                        else:
                            yield {"type": "status", "message": f"ページ {page_num} をスキップ"}
                    except Exception as e:
                        retries += 1
                        if retries >= 3:
                            break
                        await asyncio.sleep(2)
            yield {"type": "reviews_complete", "reviews": all_reviews, "total": total_reviews}
        except Exception as e:
            yield {"type": "error", "message": f"スクレイピング中にエラー: {str(e)}"}
        finally:
            await browser.close()


async def get_rakuten_review_url(page, original_url: str) -> str:
    try:
        review_link = await page.query_selector("a[href*='review']")
        if review_link:
            href = await review_link.get_attribute("href")
            if href and "review" in href:
                if href.startswith("http"):
                    return href.split("?")[0]
                else:
                    return "https://www.rakuten.co.jp" + href.split("?")[0]
    except:
        pass
    match = re.search(r"item\.rakuten\.co\.jp/([^/]+)/([^/?]+)", original_url)
    if match:
        shop_id = match.group(1)
        item_id = match.group(2)
        return f"https://review.rakuten.co.jp/item/1/{shop_id}:{item_id}/1/"
    return ""


async def get_rakuten_total_reviews(page) -> int:
    try:
        content = await page.content()
        for pattern in [r"([\d,]+)\s*件", r"全([\d,]+)件"]:
            match = re.search(pattern, content)
            if match:
                return int(match.group(1).replace(",", ""))
    except:
        pass
    reviews = await extract_rakuten_reviews(page)
    return len(reviews)


async def extract_rakuten_reviews(page) -> list:
    reviews = []
    try:
        for selector in [".revRvwUserReview", ".review-item", "[class*='review']"]:
            elements = await page.query_selector_all(selector)
            if elements:
                for el in elements:
                    try:
                        rating = 0
                        rating_el = await el.query_selector("[class*='star'], [class*='rating'], .rvwScoreText")
                        if rating_el:
                            text = await rating_el.inner_text()
                            match = re.search(r"(\d+\.?\d*)", text)
                            if match:
                                rating = round(float(match.group(1)))
                        text_el = await el.query_selector(".revRvwUserReviewBody, .review-body, p")
                        text = ""
                        if text_el:
                            text = (await text_el.inner_text()).strip()
                        if text and len(text) > 5:
                            reviews.append({"rating": rating, "text": text})
                    except:
                        continue
                if reviews:
                    break
    except:
        pass
    return reviews
