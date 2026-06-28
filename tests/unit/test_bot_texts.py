import ast
from pathlib import Path

BOT_TEXT_SOURCE_ALLOWLIST = {Path("src/bot/texts.py")}


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_bot_modules_do_not_inline_russian_ux_texts_outside_texts_module():
    russian_literals = []
    for path in Path("src/bot").rglob("*.py"):
        if path in BOT_TEXT_SOURCE_ALLOWLIST:
            continue
        for value in _string_constants(path):
            if any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in value):
                russian_literals.append((str(path), value))

    assert russian_literals == []


def test_bot_handlers_do_not_inline_user_facing_text_literals():
    checked_methods = {"answer", "edit_text", "answer_rich"}
    offenders = []
    for path in Path("src/bot").rglob("*.py"):
        if path in BOT_TEXT_SOURCE_ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in checked_methods:
                continue
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                offenders.append((str(path), func.attr, node.args[0].value))
            for keyword in node.keywords:
                if keyword.arg in {"text", "html", "description"} and isinstance(
                    keyword.value, ast.Constant
                ):
                    if isinstance(keyword.value.value, str):
                        offenders.append((str(path), keyword.arg, keyword.value.value))

    assert offenders == []
