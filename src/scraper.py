import asyncio
import re
import urllib.parse
import browser_cookie3
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


class FragranticaScraper:
    BASE = "https://www.fragrantica.ru"
    CF_COOKIE_NAMES = {"cf_clearance", "_ga", "_ga_69SEWE02QT", "rtyt45gh"}

    def _get_cf_cookies(self) -> list:
        try:
            result = []
            for c in browser_cookie3.chrome(domain_name=".fragrantica.ru"):
                if c.name in self.CF_COOKIE_NAMES:
                    result.append({
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain if c.domain else ".fragrantica.ru",
                        "path": c.path or "/",
                    })
            return result
        except Exception:
            return []

    async def _make_context(self, p):
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        cf_cookies = self._get_cf_cookies()
        if cf_cookies:
            await context.add_cookies(cf_cookies)
        return browser, context

    async def get_favorites(self, profile_id: str) -> list:
        if not profile_id:
            raise ValueError("profile_id не задан")

        async with async_playwright() as p:
            browser, context = await self._make_context(p)
            page = await context.new_page()
            try:
                await page.goto(f"{self.BASE}/chlen/{profile_id}", wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_function(
                        """() => {
                            const h4s = document.querySelectorAll('h4');
                            return Array.from(h4s).some(h => h.textContent.includes('У меня'));
                        }""",
                        timeout=15000,
                    )
                except Exception:
                    await asyncio.sleep(3)
                await asyncio.sleep(0.5)
                content = await page.content()
                await browser.close()
                return self._parse_wardrobe(content)
            except Exception as e:
                try:
                    await page.screenshot(path="error.png", timeout=5000)
                except Exception:
                    pass
                await browser.close()
                raise e

    async def _translate_query(self, query: str) -> str:
        """Переводит запрос на английский через Groq если он на русском."""
        if not re.search(r"[а-яёА-ЯЁ]", query):
            return query
        try:
            from groq import AsyncGroq
            import os
            client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Translate this perfume name/query to English for searching on Fragrantica. "
                        f"Return ONLY the translated text, nothing else: {query}"
                    )
                }],
                max_tokens=50,
                temperature=0,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return query

    async def search_perfume(self, query: str) -> dict | None:
        """Ищет аромат на Fragrantica, возвращает первый результат с деталями."""
        query = await self._translate_query(query)

        # Шаг 1: поиск — отдельный playwright-процесс
        async with async_playwright() as p:
            browser, context = await self._make_context(p)
            page = await context.new_page()
            try:
                search_url = f"{self.BASE}/search/?query={urllib.parse.quote(query)}"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                content = await page.content()
            finally:
                await browser.close()

        soup = BeautifulSoup(content, "html.parser")
        perfume_url = self._find_best_search_result(soup, query)
        if not perfume_url:
            return None

        # Шаг 2: страница аромата — свежий playwright-процесс
        async with async_playwright() as p2:
            browser2, context2 = await self._make_context(p2)
            page2 = await context2.new_page()
            try:
                await page2.goto(perfume_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page2.wait_for_function(
                        "() => { const p = document.querySelector('#pyramid'); "
                        "return p && p.textContent.includes('ноты'); }",
                        timeout=12000,
                    )
                except Exception:
                    await asyncio.sleep(3)
                await asyncio.sleep(0.5)
                content2 = await page2.content()
            finally:
                await browser2.close()

        return self._parse_perfume_page(content2, perfume_url)

    def _parse_perfume_page(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")

        # Название и бренд из URL как fallback
        name = ""
        brand = ""
        m = re.search(r"/perfume/([^/]+)/([^/]+)-\d+\.html", url)
        if m:
            brand = m.group(1).replace("-", " ")
            name = m.group(2).replace("-", " ")
            name = f"{brand} {name}"
        # Пробуем получить имя со страницы
        h1 = soup.find("h1")
        if h1:
            h1_text = h1.get_text(strip=True)
            # Убираем суффиксы пола
            for suffix in ["для мужчин и женщин", "для женщин", "для мужчин", "унисекс"]:
                h1_text = h1_text.replace(suffix, "").strip()
            if len(h1_text) > 5 and "fragrantica" not in h1_text.lower():
                name = h1_text
        brand_tag = soup.find("span", itemprop="name")
        if brand_tag:
            brand = brand_tag.get_text(strip=True)

        # Ноты — парсим сырой текст пирамиды по ключевым словам
        notes_text = ""
        pyramid = soup.find("div", id="pyramid")
        if pyramid:
            raw = pyramid.get_text(separator=" ", strip=True)
            for phrase in ["Пирамида парфюма", "Показать голоса", "Скрыть метки",
                           "Голосовать за", "Голосуйте", "Композиция аромата",
                           "ингредиенты", "по аромату", "по нотам",
                           "Определите по шкале", "только те ноты",
                           "которые вы слышите в аромате", "интенсивности"]:
                raw = raw.replace(phrase, "")
            parts = {}
            for label, key in [("верхние ноты", "Верхние"), ("средние ноты", "Средние"), ("базовые ноты", "Базовые")]:
                m2 = re.search(rf"{label}\s+(.+?)(?=верхние ноты|средние ноты|базовые ноты|$)", raw, re.IGNORECASE)
                if m2:
                    parts[key] = m2.group(1).strip()
            if parts:
                notes_text = "\n".join(f"• *{k}:* {v}" for k, v in parts.items())
            else:
                notes_text = re.sub(r"\s+", " ", raw).strip()[:300]

        # Год выпуска
        year = ""
        year_tag = soup.find("span", itemprop="datePublished")
        if year_tag:
            year = year_tag.get_text(strip=True)

        return {
            "name": name,
            "brand": brand,
            "year": year,
            "notes_text": notes_text,
            "url": url,
        }

    def _find_best_search_result(self, soup, query: str) -> str | None:
        query_words = set(re.sub(r"[^a-zA-Z0-9]", " ", query).lower().split())
        best_url = None
        best_score = 0  # требуем хотя бы 1 совпадение

        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.search(r"/perfume/[^/]+/[^/]+-\d+\.html", href):
                continue
            if href in seen:
                continue
            seen.add(href)
            href_words = set(re.sub(r"[^a-z0-9]", " ", href.lower()).split())
            score = len(query_words & href_words)
            if score > best_score:
                best_score = score
                best_url = f"{self.BASE}{href}" if href.startswith("/") else href

        return best_url

    def _parse_wardrobe(self, html: str) -> list:
        soup = BeautifulSoup(html, "html.parser")
        perfumes = []
        seen = set()

        for h4 in soup.find_all("h4"):
            if "У меня есть" not in h4.get_text(strip=True):
                continue
            parent = h4.parent
            for _ in range(8):
                if parent is None:
                    break
                links = parent.find_all("a", href=lambda h: h and "/perfume/" in h)
                if links:
                    for a in links:
                        href = a["href"]
                        if href in seen:
                            continue
                        seen.add(href)
                        m = re.search(r"/perfume/([^/]+)/([^/]+)-(\d+)\.html", href)
                        if not m:
                            continue
                        brand = m.group(1).replace("-", " ")
                        name_raw = m.group(2).replace("-", " ")
                        full_url = f"{self.BASE}{href}" if href.startswith("/") else href
                        perfumes.append({"name": f"{brand} {name_raw}", "link": full_url})
                    break
                parent = parent.parent

        return perfumes
