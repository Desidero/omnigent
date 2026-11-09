// Timing for the git-reference autolink on a long message. Copied into
// web/src/lib by run_bench.sh (vitest only discovers files under src/) and
// removed afterwards. Writes its numbers to GIT_REFS_BENCH_OUT.
//
// Three measurements, each the median of several runs:
//   scan      findGitReferences over the raw text
//   transform remarkGitReferences over a parsed-shaped mdast of the text
//   render    FilePathAwareMessageResponse in jsdom, with and without a repository

import { writeFileSync } from "node:fs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { FileViewerContext } from "@/shell/FileViewerContext";
import { FilePathAwareMessageResponse } from "@/components/blocks/ChatMarkdown";
import {
  findGitReferences,
  remarkGitReferences,
  type GitReferenceRepository,
} from "@/lib/gitReferences";

const REPOSITORY: GitReferenceRepository = {
  provider: "github",
  host: "github.com",
  repository: "owner/repo",
  requestPrefix: "#",
};

const FILE_VIEWER = {
  openFile: () => {},
  openGithubTab: () => {},
  isChangedPath: () => false,
  conversationId: undefined,
  workspaceRoot: null,
  workspaceHome: null,
};

// Three ~40-45 KB messages, under the 50 KB cap above which chat skips
// markdown entirely: 400 bullet lines each, with no references, a dozen in
// all, or four per line (one of them in a code span, which stays plain).
const LINE_COUNT = 200;
function message(referencesPerLine: (index: number) => string): string {
  return Array.from(
    { length: LINE_COUNT },
    (_, index) =>
      `- Change ${index}: ${referencesPerLine(index)} touched \`src/file${index}.ts\` ` +
      "and the explanation runs on for a while so the line is as long as prose tends to be.",
  ).join("\n");
}
const MESSAGES = {
  none: message(() => "reported earlier and fixed later"),
  typical: message((index) =>
    index % 33 === 0 ? `reported in #${1000 + index}, fixed by PR #${2000 + index}` : "reported and fixed",
  ),
  dense: message(
    (index) =>
      `reported in #${1000 + index}, fixed by PR #${2000 + index} ` +
      `(see owner/other#${index}); the span \`#${index}\` stays plain,`,
  ),
};

function median(samples: number[]): number {
  const sorted = [...samples].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

function time(runs: number, work: () => void): number {
  const samples: number[] = [];
  for (let run = 0; run < runs; run += 1) {
    const start = performance.now();
    work();
    samples.push(performance.now() - start);
  }
  return median(samples);
}

function paragraphTree(text: string) {
  return {
    type: "root",
    children: text.split("\n").map((line) => ({
      type: "paragraph",
      children: [{ type: "text", value: line }],
    })),
  };
}

function renderMessage(text: string, repository: GitReferenceRepository | null): number {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const start = performance.now();
  render(
    <QueryClientProvider client={client}>
      <FileViewerContext.Provider value={{ ...FILE_VIEWER, gitRepository: repository }}>
        <FilePathAwareMessageResponse mode="static">{text}</FilePathAwareMessageResponse>
      </FileViewerContext.Provider>
    </QueryClientProvider>,
  );
  const elapsed = performance.now() - start;
  cleanup();
  return elapsed;
}

it(
  "times the autolink on long messages",
  () => {
    const results: Record<string, unknown> = {};
    for (const [shape, text] of Object.entries(MESSAGES)) {
      const references = findGitReferences(text).length;
      const scanMs = time(20, () => findGitReferences(text));
      const transformMs = time(20, () => remarkGitReferences(REPOSITORY)(paragraphTree(text)));
      // Warm the markdown pipeline (lazy plugins, first-parse caches) before timing.
      renderMessage(text, null);
      renderMessage(text, REPOSITORY);
      const renderWithoutMs = median(Array.from({ length: 5 }, () => renderMessage(text, null)));
      const renderWithMs = median(Array.from({ length: 5 }, () => renderMessage(text, REPOSITORY)));
      results[shape] = {
        message_bytes: text.length,
        references_in_text: references,
        scan_ms: Number(scanMs.toFixed(3)),
        transform_ms: Number(transformMs.toFixed(3)),
        render_without_repository_ms: Number(renderWithoutMs.toFixed(1)),
        render_with_repository_ms: Number(renderWithMs.toFixed(1)),
      };
    }
    writeFileSync(
      process.env.GIT_REFS_BENCH_OUT ?? "autolink-bench.json",
      JSON.stringify(results, null, 2) + "\n",
    );
    console.log(JSON.stringify(results, null, 2));

    // Sanity: the dense render links every prose reference and no code-span one.
    render(
      <QueryClientProvider client={new QueryClient()}>
        <FileViewerContext.Provider value={{ ...FILE_VIEWER, gitRepository: REPOSITORY }}>
          <FilePathAwareMessageResponse mode="static">{MESSAGES.dense}</FilePathAwareMessageResponse>
        </FileViewerContext.Provider>
      </QueryClientProvider>,
    );
    expect(screen.getAllByRole("link")).toHaveLength(3 * LINE_COUNT);
  },
  120_000,
);
