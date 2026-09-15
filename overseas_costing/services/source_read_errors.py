"""Typed failures shared by trusted source readers and AI review workers."""


class SourceIntegrityError(RuntimeError):
    """A server-owned source identity, snapshot, or relationship changed."""

