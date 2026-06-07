# WiseFood Client

A small, robust Python client for accessing and populating the data infrastructure of
the **WiseFood** platform.

The package ships **two clients**:

| Client | Import | API | Resources |
|--------|--------|-----|-----------|
| `DataClient` | `from wisefood import DataClient` | Data / Catalog API | articles, artifacts, guides, guidelines, textbooks, textbook passages, FCTables |
| `Client` | `from wisefood import Client` | Core API | households, members, profiles |

Both authenticate the same way (user **or** machine-to-machine credentials) and share a
retrying, connection-pooled HTTP core.

```bash
pip install wisefood
```

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)
print(client.articles.search("mediterranean diet", limit=5))
```

```{toctree}
:caption: Getting Started
:maxdepth: 2

installation
quickstart
authentication
```

```{toctree}
:caption: Core Concepts
:maxdepth: 2

concepts/entities-and-proxies
concepts/collections
concepts/identifiers-and-urns
concepts/search
concepts/error-handling
```

```{toctree}
:caption: Resource Guides
:maxdepth: 2

guides/articles
guides/guides-and-guidelines
guides/textbooks
guides/artifacts
guides/fctables
guides/households-and-members
```

```{toctree}
:caption: Integrations
:maxdepth: 2

integrations/ai-agents
```

```{toctree}
:caption: Reference
:maxdepth: 2

reference/api
reference/low-level-http
changelog
contributing
```
