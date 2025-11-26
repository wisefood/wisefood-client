"""
IPython/Jupyter key-completion support for bracket-style access:

    client.articles["he<TAB>

This integrates with IPython’s tab completion protocol and works for
any collection subclassing BaseCollectionProxy.
"""

import re
from IPython import get_ipython
from wisefood.entities.base import BaseCollectionProxy


def completion_for_collections(self, event):
    """
    Return suggested slugs for expressions of the form:

        <object>.<collection>["<prefix>

    Only triggers when <collection> is a BaseCollectionProxy.
    """

    line = event.line

    # Match:   variable.collection["prefix
    match = re.search(r'(\w+)\.(\w+)\["([^"]*)$', line)
    if not match:
        return []

    var_name, attr_name, prefix = match.groups()

    shell = get_ipython()
    if shell is None:
        return []

    # Resolve the base object (e.g. "client")
    base_obj = shell.user_ns.get(var_name)
    if base_obj is None:
        return []

    # Resolve the collection proxy (e.g. "articles")
    collection = getattr(base_obj, attr_name, None)
    if not isinstance(collection, BaseCollectionProxy):
        return []

    try:
        slugs = collection.slugs()
    except Exception:
        return []

    # Prefix-based completion (not fuzzy)
    return [s for s in slugs if s.startswith(prefix)]


# Register the completer with IPython
ip = get_ipython()
if ip:
    ip.set_hook("complete_command", completion_for_collections)
