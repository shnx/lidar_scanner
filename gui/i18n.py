"""
Lightweight i18n helper — loads translations.yaml and
provides a t() function for key lookup.
"""

import logging
from pathlib import Path
from typing import Dict, Any
import yaml

logger = logging.getLogger(__name__)

_translations: Dict[str, Dict[str, str]] = {}
_current_lang: str = "en"


def load(yaml_path: Path) -> None:
    global _translations
    with open(yaml_path, "r", encoding="utf-8") as f:
        _translations = yaml.safe_load(f) or {}


def set_language(lang: str) -> None:
    global _current_lang
    if lang in _translations:
        _current_lang = lang
    else:
        logger.warning(f"Language '{lang}' not found in translations")


def current_language() -> str:
    return _current_lang


def t(key: str, **kwargs: Any) -> str:
    """Translate key in current language; falls back to English then key itself."""
    lang_dict = _translations.get(_current_lang, {})
    text = lang_dict.get(key)
    if text is None:
        text = _translations.get("en", {}).get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def is_rtl() -> bool:
    return _current_lang == "ar"
