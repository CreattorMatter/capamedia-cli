"""Core modules: canonical loading, frontmatter parsing, schema validation."""

from capamedia_cli.core.canonical import CanonicalAsset, load_canonical_assets
from capamedia_cli.core.frontmatter import parse_frontmatter, serialize_frontmatter

__all__ = [
    "CanonicalAsset",
    "load_canonical_assets",
    "parse_frontmatter",
    "serialize_frontmatter",
]
