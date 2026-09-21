"""dca_frontier — deterministic Frontier Communications provider package.

Live crawl: ``dca_frontier.crawl.crawl_address`` → legacy nodriver L6.
Seeds / decoder / offer_extractor are deadshot packaging artifacts.
"""

from dca_frontier.seeds import frontier_seed_recipe

__all__ = ["frontier_seed_recipe", "crawl_address"]


def __getattr__(name: str):
    if name == "crawl_address":
        from dca_frontier.crawl import crawl_address

        return crawl_address
    raise AttributeError(name)
