from __future__ import annotations

import importlib.util
import json
import logging
import re
from dataclasses import dataclass

from .config import Settings

logger = logging.getLogger(__name__)

# JSON schema for the structured Claude response. Kept within the documented
# structured-output limits (no length/numeric constraints, additionalProperties
# must be false). Works on claude-haiku-4-5.
VIBE_SCHEMA = {
    'type': 'object',
    'properties': {
        'interpretation': {'type': 'string'},
        'queries': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['interpretation', 'queries'],
    'additionalProperties': False,
}

SYSTEM_PROMPT = (
    'You translate a free-form mood, vibe, or activity description into concrete '
    'music search queries for a music search engine (YouTube-style). '
    'Return a short, friendly one-sentence interpretation of the vibe and a list '
    'of distinct, concrete search queries. Each query should be the kind of text a '
    'person would type to find matching music: genre + mood + descriptors, an '
    'artist name, a style, or a scene (for example "lo-fi rainy night beats", '
    '"energetic running synthwave", "calm acoustic morning"). '
    'If listening history is provided, let it bias a couple of queries toward that '
    'taste, but still cover the requested vibe. Do not invent track titles that '
    'may not exist; prefer genres, styles, and well-known artists. '
    'Reply in the same language as the request.'
)

# Deterministic fallback lexicon: mood/activity keyword -> search modifiers.
# Each pattern is matched against the lowercased query (RU + EN cues).
LEXICON: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r'груст|печал|sad|melanchol|тоск', ('грустная музыка', 'sad melancholic songs', 'эмоциональная инструментальная')),
    (r'дожд|rain|осен|туман', ('lofi rainy night', 'дождливый день чилл', 'rainy ambient piano')),
    (r'ноч|night|late|вечер', ('night chill lo-fi', 'ночная музыка для души', 'midnight ambient')),
    (r'релакс|relax|спокой|calm|chill|чил', ('relaxing instrumental', 'спокойная музыка для отдыха', 'calm ambient chill')),
    (r'бодр|энерг|energy|upbeat|драйв|весел', ('энергичная музыка', 'upbeat feel good songs', 'high energy electronic')),
    (r'пробежк|бег|run|workout|трен|gym|спорт', ('workout running music', 'музыка для тренировки', 'gym motivation mix')),
    (r'работ|код|focus|study|учеб|концентрац', ('focus deep work music', 'музыка для работы и концентрации', 'study beats instrumental')),
    (r'танц|dance|вечеринк|party|клуб', ('dance party hits', 'танцевальная музыка', 'club electronic mix')),
    (r'роман|любов|love|свидан', ('romantic songs', 'романтичная музыка', 'love ballads')),
    (r'дорог|road|поездк|trip|driv|маршрут', ('road trip driving songs', 'музыка в дорогу', 'driving rock playlist')),
    (r'утр|morning|кофе|coffee', ('calm morning acoustic', 'утренняя музыка для настроения', 'soft coffee jazz')),
    (r'90|ретро|retro|nostalg|ностальг|80', ('ретро хиты', 'retro nostalgia hits', '80s 90s classics')),
)


@dataclass
class VibeOutput:
    interpretation: str
    queries: list[str]
    source: str  # 'ai' or 'lexicon'


class VibeInterpreter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None  # lazily constructed AsyncAnthropic

    def ai_available(self) -> bool:
        return bool(self.settings.anthropic_api_key) and importlib.util.find_spec('anthropic') is not None

    async def interpret(self, query: str, taste: list[str]) -> VibeOutput:
        cleaned = query.strip()
        if self.ai_available():
            result = await self._interpret_ai(cleaned, taste)
            if result is not None:
                return result
        return self._interpret_lexicon(cleaned, taste)

    async def _interpret_ai(self, query: str, taste: list[str]) -> VibeOutput | None:
        try:
            import anthropic
        except ImportError:
            return None
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)

        taste_line = ', '.join(taste[:10]) if taste else '(none provided)'
        user_request = query or 'Pick music that fits my taste.'
        prompt = (
            f'Mood/vibe request: {user_request}\n'
            f'Listening history (recent, most relevant first): {taste_line}\n'
            f'Produce up to {self.settings.vibe_queries} concrete search queries.'
        )
        try:
            response = await self._client.messages.create(
                model=self.settings.ai_model,
                max_tokens=700,
                system=SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': prompt}],
                output_config={'format': {'type': 'json_schema', 'schema': VIBE_SCHEMA}},
            )
        except anthropic.APIError as exc:
            logger.warning('Vibe AI request failed: %s', exc)
            return None
        except Exception:  # pragma: no cover - defensive, never break the bot
            logger.exception('Unexpected vibe AI failure')
            return None

        if getattr(response, 'stop_reason', None) == 'refusal':
            logger.info('Vibe AI refused the request; using lexicon fallback')
            return None

        text = next((block.text for block in response.content if block.type == 'text'), '')
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning('Vibe AI returned non-JSON output')
            return None

        queries = self._clean_queries(data.get('queries'))
        if not queries:
            return None
        interpretation = str(data.get('interpretation') or '').strip() or 'Подобрал под твой запрос'
        return VibeOutput(interpretation=interpretation, queries=queries, source='ai')

    def _interpret_lexicon(self, query: str, taste: list[str]) -> VibeOutput:
        lowered = query.lower()
        queries: list[str] = []
        for pattern, modifiers in LEXICON:
            if re.search(pattern, lowered):
                queries.extend(modifiers)
        # Always include the raw request as a query so we never return nothing.
        if query:
            queries.insert(0, query)
        # Bias one slot toward the user's taste, if known.
        if taste:
            queries.append(taste[0])
        if not queries:
            queries = ['популярная музыка', 'popular songs playlist', 'best music mix']
        deduped = self._clean_queries(queries)
        interpretation = (
            f'Подобрал по запросу «{query}»' if query else 'Подборка под твой вкус'
        )
        return VibeOutput(interpretation=interpretation, queries=deduped, source='lexicon')

    def _clean_queries(self, raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = str(item).strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                result.append(text)
            if len(result) >= self.settings.vibe_queries:
                break
        return result
