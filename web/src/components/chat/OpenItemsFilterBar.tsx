import type { ReactNode } from "react";
import { SearchIcon, XIcon } from "lucide-react";
import {
  OPEN_ITEM_STATUS_NAMES,
  hasOpenItemFilters,
  kindName,
  NO_OPEN_ITEM_FILTERS,
  type OpenItemFacetCounts,
  type OpenItemFilters,
  type OpenItemGrouping,
} from "@/lib/openItemFilters";
import type { OpenItemStatus } from "@/lib/openItems";
import { cn } from "@/lib/utils";

const GROUPINGS: { value: OpenItemGrouping; name: string }[] = [
  { value: "status", name: "Status" },
  { value: "topic", name: "Topic" },
  { value: "kind", name: "Kind" },
];

function FilterChip({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-xs tabular-nums transition-colors",
        pressed
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/**
 * Search, one sideways-scrolling row of chips (status with counts, kind,
 * topic) and the grouping for the Open items panel. A chip selects its value
 * in its facet; selecting it again clears the facet.
 */
export function OpenItemsFilterBar({
  filters,
  counts,
  grouping,
  onFiltersChange,
  onGroupingChange,
}: {
  filters: OpenItemFilters;
  counts: OpenItemFacetCounts;
  grouping: OpenItemGrouping;
  onFiltersChange: (filters: OpenItemFilters) => void;
  onGroupingChange: (grouping: OpenItemGrouping) => void;
}) {
  const toggle = <Facet extends "status" | "kind" | "topic">(
    facet: Facet,
    value: OpenItemFilters[Facet],
  ) => onFiltersChange({ ...filters, [facet]: filters[facet] === value ? null : value });
  return (
    <div className="flex flex-col gap-1.5 px-3 pb-2" data-testid="open-items-filters">
      <div className="flex items-center gap-2">
        <label className="flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-md border border-border bg-background px-2">
          <SearchIcon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <input
            type="search"
            value={filters.query}
            placeholder="Search items"
            aria-label="Search open items"
            className="min-w-0 flex-1 bg-transparent text-xs outline-none"
            onChange={(event) => onFiltersChange({ ...filters, query: event.target.value })}
          />
        </label>
        <select
          value={grouping}
          aria-label="Group items by"
          className="h-7 shrink-0 rounded-md border border-border bg-background px-1 text-xs"
          onChange={(event) => onGroupingChange(event.target.value as OpenItemGrouping)}
        >
          {GROUPINGS.map(({ value, name }) => (
            <option key={value} value={value}>
              {`By ${name.toLowerCase()}`}
            </option>
          ))}
        </select>
      </div>
      <div
        role="group"
        aria-label="Filter open items"
        className="flex items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {hasOpenItemFilters(filters) && (
          <button
            type="button"
            aria-label="Clear filters"
            className="flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs text-link hover:underline"
            onClick={() => onFiltersChange(NO_OPEN_ITEM_FILTERS)}
          >
            <XIcon className="size-3" aria-hidden="true" />
            Clear
          </button>
        )}
        {(["open", "answered", "closed"] as OpenItemStatus[]).map((status) => (
          <FilterChip
            key={status}
            pressed={filters.status === status}
            onClick={() => toggle("status", status)}
          >
            {`${OPEN_ITEM_STATUS_NAMES[status]} ${counts.status[status]}`}
          </FilterChip>
        ))}
        {counts.kinds.length > 1 &&
          counts.kinds.map(({ kind, count }) => (
            <FilterChip
              key={kind}
              pressed={filters.kind === kind}
              onClick={() => toggle("kind", kind)}
            >
              {`${kindName(kind)} ${count}`}
            </FilterChip>
          ))}
        {counts.topics.map(({ topic, count }) => (
          <FilterChip
            key={topic}
            pressed={filters.topic === topic}
            onClick={() => toggle("topic", topic)}
          >
            {`#${topic} ${count}`}
          </FilterChip>
        ))}
      </div>
    </div>
  );
}
