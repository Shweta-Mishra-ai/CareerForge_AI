"""Ingestion errors. Every message is written for end users (no stack traces, no internals)."""


class IngestError(ValueError):
    """A document/URL could not be turned into usable input."""


class UnsupportedFormat(IngestError):
    pass


class FileTooLarge(IngestError):
    pass


class EncryptedDocument(IngestError):
    pass


class UnreadableDocument(IngestError):
    pass


class EmptyDocument(IngestError):
    """No extractable text (typically a scanned image)."""


class UnsafeURL(IngestError):
    """URL refused by the SSRF guard or by policy."""


class FetchFailed(IngestError):
    pass


class SourceNotSupported(IngestError):
    """E.g. a LinkedIn profile URL: the site cannot be read, and we say so honestly."""
