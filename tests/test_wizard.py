from ui import wizard


def test_custom_keyword_can_replace_predefined_categories(monkeypatch):
    answers = iter([[wizard.CUSTOM_CATEGORY], "solar panel installer"])
    monkeypatch.setattr(wizard, "_ask", lambda _prompt: next(answers))

    assert wizard._ask_categories() == ["solar panel installer"]


def test_custom_keyword_can_be_added_to_predefined_categories(monkeypatch):
    answers = iter([["plumbers", wizard.CUSTOM_CATEGORY], "drain cleaning"])
    monkeypatch.setattr(wizard, "_ask", lambda _prompt: next(answers))

    assert wizard._ask_categories() == ["plumbers", "drain cleaning"]
