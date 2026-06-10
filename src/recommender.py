import os
import json
from groq import AsyncGroq

class PerfumeRecommender:
    def __init__(self):
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

    async def get_recommendations(self, favorites_list):
        if not favorites_list:
            fav_names = "популярные свежие и древесные ароматы"
        else:
            fav_names = ", ".join([p['name'] for p in favorites_list])

        prompt = f"""У пользователя в избранном на Fragrantica следующие ароматы: {fav_names}.
На основе его вкуса порекомендуй 3 новых аромата, которых НЕТ в этом списке.
Для каждого аромата напиши:
1. Название (бренд + название аромата)
2. Почему он подойдет (подробно, со ссылкой на конкретные ноты из избранного)
3. Основные ноты

Ответ дай СТРОГО в формате JSON без лишнего текста:
{{
  "recommendations": [
    {{"name": "Название", "reason": "Почему подойдет", "notes": "Верхние, средние и базовые ноты"}}
  ]
}}"""

        response = await self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2048,
        )

        text = response.choices[0].message.content.replace('```json', '').replace('```', '').strip()
        return json.loads(text)
