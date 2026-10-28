"""Count the tokens the git-reference instruction adds to a system prompt.

Run from the checkout root with its virtualenv::

    .venv/bin/python <scratch>/git-refs/bench/token_count.py
"""

import tiktoken

from omnigent.runtime.prompt import GIT_REFERENCE_NOTATION_INSTRUCTION

for encoding_name in ("o200k_base", "cl100k_base"):
    encoding = tiktoken.get_encoding(encoding_name)
    # The composer joins instructions with a blank line, so count that separator too.
    print(f"{encoding_name}: {len(encoding.encode('\n\n' + GIT_REFERENCE_NOTATION_INSTRUCTION))} tokens")
print(f"characters: {len(GIT_REFERENCE_NOTATION_INSTRUCTION)}")
