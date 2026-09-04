import pytest

from src.content.output_guard import (
    validate_no_detective_template,
    validate_no_duplicate_echo,
    validate_opening,
    validate_telegram,
)


def test_telegram_rejects_full_article():
    text = "\n".join(
        [
            "A sharp observation.",
            "A business implication.",
            "Another paragraph.",
            "And another paragraph that should never be published to Telegram.",
        ]
    )
    with pytest.raises(ValueError, match="maximum is 3"):
        validate_telegram(text)


def test_telegram_accepts_two_line_signal():
    validate_telegram(
        "Your busiest month can be the month customers stop encountering you.\n"
        "Silence spends the recognition your business already earned."
    )


def test_detective_template_rejected_when_repeated():
    text = (
        "I figured the business had solved its marketing. "
        "I went looking for the pattern. But then I found a different explanation."
    )
    with pytest.raises(ValueError, match="detective template"):
        validate_no_detective_template(text, "blog")


def test_dictionary_opening_rejected():
    with pytest.raises(ValueError, match="dictionary-style"):
        validate_opening(
            "A London restaurant serves food and beverages to customers in a dine-in setting. "
            "The owner posts irregularly.",
            "blog",
        )


def test_duplicate_echo_rejected():
    text = (
        "The mechanism becomes visible. "
        "Customers rarely decide to forget a business when they stop seeing it. "
        "Customers rarely decide to forget a business when they stop seeing it."
    )
    with pytest.raises(ValueError, match="duplicated Echo"):
        validate_no_duplicate_echo(text, "instagram")


def test_the_guard_module_no_longer_detects_cross_platform_repetition():
    """#221: sentence recurrence across surfaces is allowed, so the detector
    that existed only to reject it was removed with its two callers."""
    import src.content.output_guard as guard

    assert not hasattr(guard, "repeated_cross_platform_phrases")
