"""Small client for Holdsport (holdsport.dk), the Danish team sports app.

Holdsport has no public, documented API. This uses two things a normal user login can reach:

- the JSON API at https://api.holdsport.dk/v1 (HTTP Basic, the same login as the app)
- the website, for declining an activity, which the API does not support

Both are undocumented and can change without notice. Every call raises HoldsportError on
anything unexpected, so a caller notices a change instead of failing silently.
"""

from .client import Holdsport, HoldsportError

__all__ = ["Holdsport", "HoldsportError"]
