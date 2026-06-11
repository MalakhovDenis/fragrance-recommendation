import asyncio
import re
import urllib.parse
from playwright.async_api import async_playwright


class PriceService:
    BASE = "https://allureparfum.ru"

    @staticmethod
    def get_search_url(perfume_name: str) -> str:
        return f"https://allureparfum.ru/search/?q={urllib.parse.quote(perfume_name)}"

    @staticmethod
    def get_fragrantica_url(perfume_name: str) -> str:
        return f"https://www.fragrantica.ru/search/?query={urllib.parse.quote(perfume_name)}"

    async def fetch_prices(self, perfume_name: str) -> dict | None:
        """
        Возвращает цену пробника (1мл или минимальный объём до 10мл) с allureparfum.ru.
        """
        search_url = self.get_search_url(perfume_name)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            try:
                result = await self._search_and_parse(context, perfume_name, search_url)
            finally:
                await browser.close()
        return result

    async def _search_and_parse(self, context, perfume_name: str, search_url: str):
        from bs4 import BeautifulSoup

        # --- Шаг 1: поиск → URL товара ---
        # Пробуем несколько вариантов запроса от длинного к короткому
        words = perfume_name.split()
        queries = [perfume_name]
        if len(words) > 2:
            queries.append(" ".join(words[:2]))    # первые 2 слова (обычно название)
            queries.append(" ".join(words[:3]))    # первые 3 слова

        product_url = None
        for query in queries:
            url = f"{self.BASE}/search/?q={urllib.parse.quote(query)}"
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)
                content = await page.content()
            except Exception:
                await page.close()
                continue
            finally:
                await page.close()

            soup = BeautifulSoup(content, "html.parser")
            product_url = self._find_best_product_link(soup, perfume_name)
            if product_url:
                break

        if not product_url:
            return None

        # --- Шаг 2: страница товара → цена пробника ---
        page2 = await context.new_page()
        try:
            await page2.goto(product_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            content2 = await page2.content()
        except Exception:
            await page2.close()
            return None
        finally:
            await page2.close()

        soup2 = BeautifulSoup(content2, "html.parser")
        price_data = self._parse_sample_price(soup2, product_url)
        image_url = self._parse_product_image(soup2)
        if price_data and image_url:
            price_data["image_url"] = image_url
        elif image_url:
            return {"image_url": image_url, "url": product_url}
        return price_data

    def _parse_product_image(self, soup) -> str:
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if "450_450" in src and "/upload/" in src:
                return f"{self.BASE}{src}" if src.startswith("/") else src
        return ""

    def _find_best_product_link(self, soup, perfume_name: str, min_score: int = 2) -> str | None:
        """Из страницы поиска выбирает наиболее подходящую ссылку на товар."""
        name_words = set(re.sub(r"[^a-zA-Z0-9]", " ", perfume_name).lower().split())

        best_link = None
        best_score = min_score - 1  # требуем хотя бы min_score совпадений

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not (href.startswith("/katalog/") and href.count("/") >= 4 and href.endswith(".html")):
                continue
            href_words = set(re.sub(r"[^a-z0-9]", " ", href.lower()).split())
            score = len(name_words & href_words)
            if score > best_score:
                best_score = score
                best_link = href

        return f"{self.BASE}{best_link}" if best_link else None

    def _parse_sample_price(self, soup, product_url: str) -> dict | None:
        """Из страницы товара берёт цену пробника (объём ≤ 10 мл)."""
        samples = []
        all_items = []

        for item in soup.find_all("div", class_="offer-item"):
            vol_el = item.find("div", class_="offer-volume")
            if not vol_el:
                continue
            vol_text = vol_el.get_text(strip=True)
            vol_match = re.search(r"(\d+(?:[.,]\d+)?)\s*мл", vol_text, re.IGNORECASE)
            if not vol_match:
                continue
            volume_ml = float(vol_match.group(1).replace(",", "."))

            price_el = item.find(class_="offer-price--inner")
            if not price_el:
                continue
            price_text = re.sub(r"\s+", "", price_el.get_text(strip=True))
            price_match = re.search(r"\d+", price_text)
            if not price_match:
                continue
            price_rub = int(price_match.group(0))

            avail_el = item.find(class_="offer-availability")
            available = bool(avail_el and "наличии" in avail_el.get_text())

            entry = {
                "volume_ml": volume_ml,
                "price_rub": price_rub,
                "price_per_ml": round(price_rub / volume_ml),
                "available": available,
            }
            all_items.append(entry)
            if volume_ml <= 10:
                samples.append(entry)

        # Предпочитаем пробники; если нет — берём из всех
        pool = samples if samples else all_items
        if not pool:
            return None

        # Из пула берём наименьший объём в наличии; если нет в наличии — просто наименьший
        pool_available = [e for e in pool if e["available"]]
        chosen = min(pool_available or pool, key=lambda e: e["volume_ml"])

        return {
            "price_rub": chosen["price_rub"],
            "volume_ml": chosen["volume_ml"],
            "price_per_ml": chosen["price_per_ml"],
            "available": chosen["available"],
            "url": product_url,
        }
