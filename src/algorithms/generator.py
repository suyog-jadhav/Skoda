from src.core.gh_client import GHClient
from src.rcsp.filter import RouteCandidate

class RouteGenerator:
    def __init__(self, client: GHClient):
        self.client = client

    def generate_all(self, source, destination):
        candidates = []

        # 1. Standard A* (Fastest)
        print(f"Generating A* path...")
        res_astar = self.client.get_route(source, destination, algo="astar", ch_disable=True)
        if res_astar and "paths" in res_astar:
            for p in res_astar["paths"]:
                candidates.append(RouteCandidate(p, {"algo": "A*", "tag": "Baseline"}))

        # 2. Dijkstra (Optimum check)
        # Note: Often returns same geometry as A* but ensures optimality
        print(f"Generating Dijkstra path...")
        res_dijk = self.client.get_route(source, destination, algo="dijkstra", ch_disable=True)
        if res_dijk and "paths" in res_dijk:
             # Only add if distinct? For demo, we add it to show comparison stats
            for p in res_dijk["paths"]:
                candidates.append(RouteCandidate(p, {"algo": "Dijkstra", "tag": "Exact"}))

        # 3. Alternatives
        print(f"Generating Alternative paths...")
        res_alt = self.client.get_route(source, destination, alternatives=True, ch_disable=True)
        if res_alt and "paths" in res_alt:
            for p in res_alt["paths"]:
                # Check duplicate geometry to maximize distinctness
                candidates.append(RouteCandidate(p, {"algo": "Alternative", "tag": "Alt"}))

        # 4. CH (Speed check)
        # CH requires pre-calculated profile, cannot disable CH if we want to test its speed
        # But CH usually doesn't support details/flexible weighting as easily in older GH versions via API
        # We try to fetch it just for metrics
        print(f"Generating CH path...")
        res_ch = self.client.get_route(source, destination, ch_disable=False)
        if res_ch and "paths" in res_ch:
             for p in res_ch["paths"]:
                candidates.append(RouteCandidate(p, {"algo": "CH", "tag": "HighSpeed"}))

        return candidates
