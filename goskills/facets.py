"""Public-text-only deterministic schema; no benchmark task names or outcomes.

This dictionary is a new, versioned reconstruction, not the omitted original
dictionary. Prefixes preserve facet categories in coverage-debt accounting.
"""
import re

CATEGORIES = ("core", "tech", "op", "artifact", "constraint", "failure", "check")
STOP = frozenset("a an the and or to of in on for with from by is are be as at this that it its you your use using should must can will file files task output input create make required please need then when into do not no all any only have has which their these those also other each more same given return result run code data new before after without following ensure implement implementation based directory path available provided".split())
TECH = {
    "python": (), "javascript": ("js",), "typescript": ("ts",), "react": ("reactjs", "react.js"),
    "nextjs": ("next.js",), "nodejs": ("node.js", "node"), "pandas": (), "numpy": ("np",),
    "scipy": (), "pytorch": ("torch",), "tensorflow": (), "jax": (), "matplotlib": (),
    "opencv": ("cv2",), "ffmpeg": (), "ffprobe": (), "threejs": ("three.js",),
    "blender": (), "trimesh": (), "sympy": (), "lean4": ("lean 4",), "coq": (),
    "latex": (), "java": (), "scala": (), "erlang": (), "rust": (), "golang": ("go language",),
    "spring": ("spring boot",), "jakarta": (), "hibernate": (), "jackson": (),
    "postgresql": ("postgres",), "sqlite": (), "mysql": (), "mongodb": (), "redis": (),
    "docker": (), "kubernetes": ("k8s",), "terraform": (), "azure": (), "aws": (),
    "pytest": (), "unittest": (), "jest": (), "playwright": (), "vitest": (),
    "flink": (), "druid": (), "suricata": (), "syzkaller": (), "pddl": (),
    "pandapower": (), "casadi": (), "qutip": (), "librosa": (), "whisper": (),
    "openpyxl": (), "python-docx": (), "python-pptx": (), "pdfplumber": (),
    "pymupdf": ("fitz",), "pillow": ("pil",), "tesseract": (), "beautifulsoup": ("bs4",),
    "scikit-learn": ("sklearn",), "xgboost": (), "networkx": (), "igraph": (),
}
FORMATS = frozenset("json jsonl csv tsv xml yaml yml toml txt md html css pdf docx pptx xlsx xls parquet arrow hdf5 h5 npy npz png jpg jpeg svg webp mp4 mov wav mp3 srt vtt stl obj ply gltf glb pddl lean tex sql zip tar gz".split())
OPS = {"parse": r"\bpars(?:e|es|ing|er)\b", "convert": r"\bconvert\w*\b",
       "extract": r"\bextract\w*\b", "validate": r"\bvalidat\w*\b",
       "calculate": r"\b(?:calculat\w*|comput\w*)\b", "optimize": r"\boptimi[sz]\w*\b",
       "repair": r"\b(?:fix|repair|debug|patch)\w*\b", "render": r"\brender\w*\b",
       "analyze": r"\banaly[sz]\w*\b", "train": r"\btrain\w*\b",
       "test": r"\btest(?:s|ing)?\b", "prove": r"\b(?:prov(?:e|ing)|proof)\b",
       "search": r"\b(?:search|retriev)\w*\b", "transcribe": r"\btranscrib\w*\b",
       "simulate": r"\bsimulat\w*\b", "plot": r"\bplot\w*\b"}
RULES = {
    "constraint": {"deterministic": r"\b(?:deterministic|reproducible|fixed seed)\b",
                   "offline": r"\b(?:offline|no network|without (?:internet|network))\b",
                   "stdlib-only": r"\b(?:standard library only|stdlib.only|no third.party)\b",
                   "no-modify-tests": r"\b(?:do not|never|must not) (?:modify|change|edit) (?:the )?tests?\b"},
    "check": {"tests": r"\b(?:unit tests?|test suite|pytest|unittest|jest|vitest)\b",
              "proof": r"\b(?:formal proof|proof obligation|theorem|lean4|lean 4)\b",
              "schema": r"\b(?:schema|exact (?:format|columns)|valid json)\b",
              "deterministic": r"\b(?:deterministic|reproducible|fixed seed)\b"},
    "failure": {"security": r"\b(?:vulnerability|injection|cve-\d+|exploit)\b",
                "numerical": r"\b(?:nan|overflow|singular|instability)\b",
                "format": r"\b(?:malformed|invalid format|parse error)\b"},
}


def tokens(text):
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_+-]*", text)
            if len(t) > 1 and t.lower() not in STOP}


def _has(text, word):
    return re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", text, re.I) is not None


def extract(text, metadata=None):
    if not isinstance(text, str):
        raise TypeError("Schema extraction requires explicit public text")
    lower = text.lower()
    result = {category: set() for category in CATEGORIES}
    result["core"] = {"core:" + t for t in tokens(text)}
    exact = set()
    for name, aliases in TECH.items():
        if _has(lower, name):
            result["tech"].add("tech:" + name)
            exact.add("tech:" + name)
        elif any(_has(lower, alias) for alias in aliases):
            result["tech"].add("tech:" + name)
    for name in FORMATS:
        if _has(lower, name) or re.search(r"\." + name + r"\b", lower):
            result["artifact"].add("artifact:" + name)
            exact.add("artifact:" + name)
    # Named APIs must be explicit identifier.identifier calls, not inferred APIs.
    for api in re.findall(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*\(", text):
        facet = "tech:api:" + api.lower()
        result["tech"].add(facet)
        exact.add(facet)
    for name, pattern in OPS.items():
        if re.search(pattern, lower):
            result["op"].add("op:" + name)
    for category, patterns in RULES.items():
        for name, pattern in patterns.items():
            if re.search(pattern, lower):
                result[category].add(category + ":" + name)
    # An explicit artifact filename is an obligation; a related format alone
    # does not prove its exact name is covered by a payload.
    for filename in re.findall(r"(?<![\w])([A-Za-z0-9_-]+\.[A-Za-z0-9]+)\b", text):
        if filename.rsplit(".", 1)[1].lower() in FORMATS:
            facet = "artifact:file:" + filename.lower()
            result["artifact"].add(facet)
            exact.add(facet)
    negative = set()
    for marker, phrase in re.findall(r"\b(do not use|must not use|avoid using|not suitable for|not for|incompatible with|unsupported|without)\s+([^.;\n]+)", lower):
        # Commas can continue a prohibited list, but an affirmative imperative
        # starts a new clause. "without changing CSV" is not "without CSV".
        if marker == "without":
            names = list(FORMATS) + [alias for name, aliases in TECH.items() for alias in (name, *aliases)]
            if not any(re.match(re.escape(name) + r"(?![\w])", phrase) for name in names):
                continue
        phrase = re.split(r"(?:,\s*|\band\s+)(?=(?:use|parse|convert|write|produce|read|calculate|emit|keep|preserve)\b)|\b(?:but|instead|then)\b|\bto\s+(?:parse|convert|write|produce|read|calculate)\b", phrase, maxsplit=1)[0]
        for name, aliases in TECH.items():
            if any(_has(phrase, alias) for alias in (name, *aliases)):
                negative.add("tech:" + name)
        for name in FORMATS:
            if _has(phrase, name):
                negative.add("artifact:" + name)
        for name, pattern in RULES["constraint"].items():
            if re.search(pattern, phrase):
                negative.add("constraint:" + name)
    if metadata:
        # Only explicit structured negative facets are accepted; metadata is
        # never evaluated as instructions or code.
        values = metadata.get("negative_facets", [])
        if isinstance(values, list):
            negative.update(x for x in values if isinstance(x, str) and ":" in x)
    for category in CATEGORIES:
        result[category].difference_update(negative)
    result["constraint"].update("constraint:avoid:" + x for x in negative)
    exact.difference_update(negative)
    exact.update(result["constraint"])
    result["negative"] = negative
    result["high_confidence"] = exact
    return {key: sorted(value) for key, value in result.items()}


def all_facets(schema):
    return set().union(*(schema.get(category, []) for category in CATEGORIES))


def enrich_skill(skill):
    metadata = skill.get("metadata", {})
    def values(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [text for item in value for text in values(item)]
        if isinstance(value, dict):
            return [text for item in value.values() for text in values(item)]
        return []
    # Public declared metadata participates offline. Paths/IDs, negative and
    # exclusive fields never become fabricated positive capabilities.
    public_metadata = []
    for container in (metadata, metadata.get("native_metadata", {}), metadata.get("upstream_vertex_attrs", {})):
        if isinstance(container, dict):
            for key in ("domain_tags", "tags", "category", "tooling", "inputs", "outputs",
                        "input_schema", "output_schema", "input_schema_json", "output_schema_json",
                        "artifacts", "description"):
                public_metadata.extend(values(container.get(key)))
    schema = extract("\n".join((skill["name"], skill.get("description", ""),
                                skill.get("text", skill.get("body", "")), *public_metadata)), metadata)
    return {**skill, "schema": schema, "facets": sorted(all_facets(schema)),
            "negative": schema["negative"], "anchors": sorted(set(schema["tech"] + schema["artifact"])),
            "checks": sorted(set(schema["check"] + schema["artifact"] + schema["constraint"])),
            "artifacts": schema["artifact"]}
