"""Sphinx configuration for the WiseFood client documentation."""

import os
import sys
from datetime import date

# Make the package importable for autodoc (src/ layout).
sys.path.insert(0, os.path.abspath("../src"))

project = "wisefood-client"
author = "WiseFood"
copyright = f"{date.today().year}, WiseFood"

# Keep in sync with pyproject.toml / src/wisefood/__init__.py.
release = "0.0.22"
version = "0.0.22"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_design",
]

# MyST (Markdown) configuration.
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "substitution",
]
myst_heading_anchors = 3

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# Don't fail the build if optional third-party imports are missing at doc time.
autodoc_mock_imports = ["IPython"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "superpowers"]

html_theme = "furo"
html_title = "WiseFood Client"
html_static_path = ["_static"]
