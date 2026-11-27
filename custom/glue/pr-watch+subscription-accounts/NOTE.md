# pr-watch+subscription-accounts

Joins: omnigent/server/routes/sessions/__init__.py, openapi.json

Each series adds session routes of its own, `/v1/sessions/{id}/pr-watch` and
`/v1/sessions/{id}/provider`, and so inserts at the same two places: the
import of its route module in the sessions router, which is kept sorted, and
its path in `openapi.json`, which is sorted too. Neither uses the other. The
pull request watch's lines come first, which is also their sorted order.
