# chat-item-comments+open-items-links-compact

`chat-item-comments` adds **Comment** to an item's preview, which switches
the composer to comment mode; `open-items-links-compact` moves the Open items
list into a panel opened from the session header, a sheet over the composer
on phones. Neither needs the other, and they build together without a join.

With both present, a comment started from a preview inside the panel would
leave the panel up over the composer. The patch closes the panel on a comment
request (`useItemCommentRequest`), as it already closes for "Show in
conversation", and points the item-comments docs and browser test at the
header's panel instead of the bar.
