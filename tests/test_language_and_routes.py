from echobridge_languages import normalize_speech_language, language_display_name
from echobridge_translation_routes import plan_translation
import pytest


def test_auto_or_forced_source():
    assert normalize_speech_language('auto') == 'auto'
    assert normalize_speech_language('pl') == 'pl'
    assert normalize_speech_language('DE') == 'de'
    assert normalize_speech_language('nonsense') == 'auto'
    assert language_display_name('pl') == 'Polish'


def test_direct_route_is_preferred():
    assert plan_translation('pl', 'de', {('pl', 'de')}) == [('pl', 'de')]


def test_via_english_if_direct_missing():
    installed = {('pl', 'en'), ('en', 'de')}
    assert plan_translation('pl', 'de', installed) == [('pl', 'en'), ('en', 'de')]


def test_install_chooses_only_required_pairs():
    available = {('pl', 'en'), ('en', 'de'), ('tr', 'en')}
    assert plan_translation('pl', 'de', set(), available) == [('pl', 'en'), ('en', 'de')]


def test_missing_pair_not_changed_to_another_language():
    with pytest.raises(RuntimeError, match='pl'):
        plan_translation('pl', 'de', {('tr', 'en'), ('en', 'de')})


def test_unknown_source_rejected():
    with pytest.raises(ValueError, match='specific source'):
        plan_translation('auto', 'de', set())
