"""Sightline agent extras: match ratings, claim checker, routine detection and translations.

Everything numeric is computed by code. Models (Azure AI Foundry, optional) only phrase text,
and a checker verifies every number and name in anything a model wrote. With no Foundry
configuration the package runs in fallback mode with template phrasing.
"""
__all__ = ["common", "ratings", "claims", "checker", "llm", "routines", "translate"]
