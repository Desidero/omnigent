"""The server's port of the chat's item-label rules, against the cases the web is tested with."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omnigent.entities.item_labels import (
    defines_label,
    extract_item_block,
    extract_label_sentence,
    item_label_title_parts,
    item_labels_in,
    links_in_markdown,
    struck_item_labels_in,
)

# web/src/lib/itemLabelCases.test.ts runs the web parser over the same file.
_CASES = json.loads(
    (Path(__file__).parents[2] / "web/src/lib/__fixtures__/itemLabelCases.json").read_text()
)


@pytest.mark.parametrize("case", _CASES, ids=[case["name"] for case in _CASES])
def test_reads_a_message_as_the_web_does(case: dict[str, Any]) -> None:
    markdown = case["markdown"]
    assert item_labels_in(markdown) == case["labels"]
    assert struck_item_labels_in(markdown) == case["struck"]
    read = {}
    for label in case["labels"]:
        title, rest = item_label_title_parts(markdown, label)
        read[label] = {
            "block": extract_item_block(markdown, label),
            "title": title,
            "rest": rest,
            "sentence": extract_label_sentence(markdown, label),
        }
    assert read == case["items"]
    links = [{"url": link.url, "text": link.text} for link in links_in_markdown(markdown)]
    assert links == case["links"]


def test_a_label_defines_an_item_only_where_it_starts_a_line() -> None:
    markdown = "As [Q2] says.\n\n- **[Q1] First.** One.\n\n`[Q3]` in code\n\n~~[R1]~~ done."
    assert defines_label(markdown, "Q1")
    assert not defines_label(markdown, "Q2")
    assert not defines_label(markdown, "Q3")
    # A struck label at the start of a line still starts it.
    assert defines_label(markdown, "R1")
