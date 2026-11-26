// The chat's label rules, checked against the cases the server's port
// (omnigent/entities/item_labels.py) is tested with, so the two stay identical.
import { describe, expect, it } from "vitest";
import {
  extractItemBlock,
  extractLabelSentence,
  itemLabelTitleParts,
  itemLabelsIn,
  struckItemLabelsIn,
} from "@/lib/itemLabels";
import { linksInMarkdown } from "@/lib/sessionLinks";
import cases from "@/lib/__fixtures__/itemLabelCases.json";

describe.each(cases)("item label case: $name", ({ markdown, labels, struck, items, links }) => {
  it("finds the labels and the struck ones", () => {
    expect(itemLabelsIn(markdown)).toEqual(labels);
    expect(struckItemLabelsIn(markdown)).toEqual(struck);
  });

  it("reads each item's block, title and sentence", () => {
    const read = Object.fromEntries(
      labels.map((label) => {
        const { title, rest } = itemLabelTitleParts(markdown, label);
        const block = extractItemBlock(markdown, label);
        return [label, { block, title, rest, sentence: extractLabelSentence(markdown, label) }];
      }),
    );
    expect(read).toEqual(items);
  });

  it("reads the links", () => {
    expect(
      linksInMarkdown(markdown).map((link) => ({ url: link.url.href, text: link.text })),
    ).toEqual(links);
  });
});
