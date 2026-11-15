"""Supported Whisper speech recognition languages (language code -> UI label).

Auto-detection is a recognition setting, NOT an Argos translation package language.
The translator's separately configured source language is used only to install offline packages.
"""

_SPEECH_LANGUAGES = {
    'af': 'Afrikaans', 'am': 'Amharic', 'ar': 'Arabic', 'as': 'Assamese',
    'az': 'Azerbaijani', 'ba': 'Bashkir', 'be': 'Belarusian', 'bg': 'Bulgarian',
    'bn': 'Bengali', 'bo': 'Tibetan', 'br': 'Breton', 'bs': 'Bosnian',
    'ca': 'Catalan', 'cs': 'Czech', 'cy': 'Welsh', 'da': 'Danish',
    'de': 'German', 'el': 'Greek', 'en': 'English', 'es': 'Spanish',
    'et': 'Estonian', 'eu': 'Basque', 'fa': 'Persian', 'fi': 'Finnish',
    'fo': 'Faroese', 'fr': 'French', 'gl': 'Galician', 'gu': 'Gujarati',
    'ha': 'Hausa', 'haw': 'Hawaiian', 'he': 'Hebrew', 'hi': 'Hindi',
    'hr': 'Croatian', 'ht': 'Haitian Creole', 'hu': 'Hungarian',
    'hy': 'Armenian', 'id': 'Indonesian', 'is': 'Icelandic', 'it': 'Italian',
    'ja': 'Japanese', 'jw': 'Javanese', 'ka': 'Georgian', 'kk': 'Kazakh',
    'km': 'Khmer', 'kn': 'Kannada', 'ko': 'Korean', 'la': 'Latin',
    'lb': 'Luxembourgish', 'ln': 'Lingala', 'lo': 'Lao', 'lt': 'Lithuanian',
    'lv': 'Latvian', 'mg': 'Malagasy', 'mi': 'Maori', 'mk': 'Macedonian',
    'ml': 'Malayalam', 'mn': 'Mongolian', 'mr': 'Marathi', 'ms': 'Malay',
    'mt': 'Maltese', 'my': 'Burmese', 'ne': 'Nepali', 'nl': 'Dutch',
    'nn': 'Nynorsk', 'no': 'Norwegian', 'oc': 'Occitan', 'pa': 'Punjabi',
    'pl': 'Polish', 'ps': 'Pashto', 'pt': 'Portuguese', 'ro': 'Romanian',
    'ru': 'Russian', 'sa': 'Sanskrit', 'sd': 'Sindhi', 'si': 'Sinhala',
    'sk': 'Slovak', 'sl': 'Slovenian', 'sn': 'Shona', 'so': 'Somali',
    'sq': 'Albanian', 'sr': 'Serbian', 'su': 'Sundanese', 'sv': 'Swedish',
    'sw': 'Swahili', 'ta': 'Tamil', 'te': 'Telugu', 'tg': 'Tajik',
    'th': 'Thai', 'tk': 'Turkmen', 'tl': 'Tagalog', 'tr': 'Turkish',
    'tt': 'Tatar', 'uk': 'Ukrainian', 'ur': 'Urdu', 'uz': 'Uzbek',
    'vi': 'Vietnamese', 'yi': 'Yiddish', 'yo': 'Yoruba', 'zh': 'Chinese',
}

SPEECH_LANGUAGES = [('auto', 'Automatic (detect spoken language)')] + sorted(
    _SPEECH_LANGUAGES.items(), key=lambda item: item[1].casefold()
)


def normalize_speech_language(value):
    """Return a supported ISO-like code or auto for unknown/old setting values."""
    code = str(value or 'auto').strip().lower()
    return code if code == 'auto' or code in _SPEECH_LANGUAGES else 'auto'


def language_display_name(code):
    """Display user-friendly language names in the result popup (including Icelandic)."""
    value = str(code or '').strip().lower()
    return _SPEECH_LANGUAGES.get(value, value or 'Unknown')
