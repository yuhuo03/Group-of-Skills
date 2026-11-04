"""Pure parser for the standalone SkillsBench retrieval transport."""
import shlex
from .skillsbench_pack import COMMANDS


def parse_query_command(command,method):
 """Return query string, None for normal bash, or raise for unsafe bridge syntax.

 Query text is passed as JSON data, never evaluated by a host shell.
 """
 try:tokens=list(shlex.shlex(command,posix=True,punctuation_chars='|&;<>()'))
 except ValueError as exc:raise ValueError('Unterminated shell quoting') from exc
 relevant=set(COMMANDS.values())
 if not tokens:return None
 first=tokens[0].split('/')[-1]
 if first not in relevant:
  # Never silently run a compound retrieval command without the bridge.
  if any(t.split('/')[-1] in relevant for t in tokens):raise ValueError('Retrieval must be a standalone command, without shell prefixes or chaining')
  return None
 if COMMANDS.get(method)!=first:raise ValueError('This retrieval command is not enabled for the selected method')
 if any(t and set(t)<=set('|&;<>()') for t in tokens):raise ValueError('Pipes, redirects and shell chaining are not supported for retrieval commands')
 if len(tokens)!=2 or not tokens[1].strip():raise ValueError('Use exactly one quoted query argument; budgets and provider settings are fixed on the host')
 return tokens[1]
