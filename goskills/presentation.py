"""Extract coherent source sections, retaining scope and example prerequisites."""
import ast
import symtable
import re

from .facets import tokens


def _sections(body):
    """Direct sections plus their ancestor sections; headings inside code ignored."""
    headings = []
    offset = 0
    fence = None
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
        elif fence is None:
            match = re.match(r"^(#{1,6})\s+(.+)", stripped)
            if match:
                headings.append((offset, len(match.group(1)), match.group(2)))
        offset += len(line)
    if not headings or headings[0][0] > 0:
        headings.insert(0, (0, 0, ""))
    sections, stack = [], []
    for i, (start, level, heading) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(body)
        while end > start and body[end - 1].isspace():
            end -= 1
        while stack and sections[stack[-1]]["level"] >= level:
            stack.pop()
        sections.append(dict(start=start, end=end, level=level, heading=heading, parents=list(stack)))
        stack.append(i)
    return sections


def source_blocks(body):
    """Public diagnostic view: complete sections rather than independent paragraphs."""
    return [(s["start"], s["end"], s["heading"]) for s in _sections(body)]


def _python_names(text):
    """Static names only; never execute examples or import their dependencies."""
    definitions, uses = set(), set()
    for match in re.finditer(r"(?ms)^\s*(`{3,}|~{3,})python\s*\n(.*?)^\s*\1\s*$", text):
        try:
            table = symtable.symtable(match.group(2), "<skill-example>", "exec")
        except SyntaxError:
            continue
        class ModuleBindings(ast.NodeVisitor):
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Store): definitions.add(node.id)
            def visit_Import(self, node):
                definitions.update(x.asname or x.name.split(".")[0] for x in node.names)
            def visit_ImportFrom(self, node):
                definitions.update(x.asname or x.name for x in node.names)
            def visit_FunctionDef(self, node): definitions.add(node.name)
            visit_AsyncFunctionDef = visit_FunctionDef
            visit_ClassDef = visit_FunctionDef
            def visit_Lambda(self, node): pass
            def visit_ListComp(self, node): pass
            visit_SetComp = visit_ListComp
            visit_DictComp = visit_ListComp
            visit_GeneratorExp = visit_ListComp
        ModuleBindings().visit(ast.parse(match.group(2)))
        uses.update(s.get_name() for s in table.get_symbols() if s.is_referenced())
        # Function/comprehension locals cannot initialize a later global name.
        # Their referenced globals may still need setup before a later call.
        pending = list(table.get_children())
        while pending:
            child = pending.pop()
            uses.update(s.get_name() for s in child.get_symbols()
                        if s.is_referenced() and s.is_global())
            pending.extend(child.get_children())
    return definitions, uses - definitions


def extractive_body(body, query, limit):
    if len(body) <= limit:
        return body, [[0, len(body)]]
    sections = _sections(body)
    # A routing tree distinguishes alternative procedures. Truncating it into
    # one apparently generic workflow changes the instructions' applicability.
    # With no semantic router, preserve the accepted prefix for these sources.
    # The fallback is disclosed by the caller; it is not claimed untruncated.
    if any(re.search(r"\bdecision\s+tree\b", s["heading"], re.I) for s in sections):
        return body[:limit], [[0, limit]]
    query_terms = tokens(query.replace("-", " ").replace("_", " "))
    dependencies, providers, ranked = [], {}, []
    for i, section in enumerate(sections):
        start, end = section["start"], section["end"]
        text = body[start:end]
        definitions, uses = _python_names(text)
        needed = set(section["parents"])
        needed.update(providers[name] for name in uses if name in providers)
        dependencies.append(needed)
        for name in definitions:
            providers[name] = i
        headings = " ".join(sections[j]["heading"] for j in [*section["parents"], i])
        terms = tokens(text.replace("-", " ").replace("_", " "))
        overlap = len(query_terms & terms)
        workflow = bool(re.search(r"workflow|recalculat|verif|validat|testing|checks?", headings, re.I))
        imperative = bool(re.search(r"\bmust\b|mandatory|required|before (?:final|deliver)", text, re.I))
        priority = 2 if overlap and (workflow or imperative) else 1 if overlap else 0
        score = (priority, len(query_terms & tokens(headings)), overlap / max(1, len(terms)) ** .5, min(overlap, 8), -i)
        content = re.sub(r"^#{1,6}\s+[^\n]+\n?", "", text).strip()
        # Empty section headers are context for descendants, not useful payload
        # in their own right. Avoid dangling headers just to fill unused space.
        if content:
            ranked.append((score, i))

    def closure(i):
        found, pending = set(), [i]
        while pending:
            j = pending.pop()
            if j not in found:
                found.add(j)
                pending.extend(dependencies[j])
        return found

    chosen = set()
    for _, i in sorted(ranked, reverse=True):
        proposed = chosen | closure(i)
        size = sum(sections[j]["end"] - sections[j]["start"] for j in proposed) + 2 * (len(proposed) - 1)
        if size <= limit:
            chosen = proposed
    spans = [[sections[j]["start"], sections[j]["end"]] for j in sorted(chosen)]
    if not spans:
        # Unheaded or oversized procedures are common in the actual library.
        # Keep the accepted nonempty prefix, explicitly marked by the caller.
        return body[:limit], [[0, limit]]
    return "\n\n".join(body[start:end] for start, end in spans), spans
