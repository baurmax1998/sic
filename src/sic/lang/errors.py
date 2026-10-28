class LangError(Exception):
    """Basisklasse für Fehler der Sprache mit optionalem Quellbereich."""

    def __init__(self, message: str, offset: int | None = None, end: int | None = None):
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.end = end

    def attach(self, offset: int | None, end: int | None = None) -> "LangError":
        if self.offset is None and offset is not None:
            self.offset = offset
            self.end = end
        return self

    def diagnostic(self, source: str, filename: str = "<input>") -> str:
        if self.offset is None:
            return f"{filename}: {self.message}"
        line = source.count("\n", 0, self.offset) + 1
        line_start = source.rfind("\n", 0, self.offset) + 1
        line_end = source.find("\n", self.offset)
        if line_end < 0:
            line_end = len(source)
        column = self.offset - line_start + 1
        excerpt = source[line_start:line_end]
        width = max(1, min((self.end or self.offset + 1) - self.offset, len(excerpt) - column + 1))
        marker = " " * (column - 1) + "^" * width
        return f"{filename}:{line}:{column}: {self.message}\n{excerpt}\n{marker}"


class LangSyntaxError(LangError):
    pass


class LangIncompleteError(LangSyntaxError):
    """Das Programm ist ein gültiges Präfix, aber noch nicht vollständig."""

    def __init__(self, expected: str = "weiterer Quelltext"):
        self.expected = expected
        super().__init__(f"Unvollständiger Quelltext; erwartet {expected}")


class LangTypeError(LangError):
    pass


class LangNameError(LangError):
    pass


class LangRuntimeError(LangError):
    pass


class LangCalculationError(LangRuntimeError):
    """Ein nicht abgefangener, mit ``err`` ausgelöster Fehlerausgang."""

    def __init__(self, name: str, payload=None, identity: tuple[str, ...] = ()):
        self.name = name
        self.payload = payload
        self.identity = identity or (name,)
        super().__init__(f"Berechnung endete mit Fehler {name!r}")
