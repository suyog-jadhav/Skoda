"""
Held-Karp Exact TSP Solver
---------------------------
Solves the Travelling Salesman Problem optimally for up to ~20 nodes
using bitmask dynamic programming (Held-Karp algorithm).

For the multi-stop logistics system, n <= 9 stops + 1 depot = 10 nodes,
making this exact solver both correct and efficient (2^10 * 10^2 ~ 100K ops).

Usage:
    solver = HeldKarp(cost_matrix)
    total_cost, path = solver.solve(start=0)
    # path is a list of node indices starting and ending at `start`
"""

INF = float('inf')


class HeldKarp:
    """
    Exact TSP solver using bitmask DP (Held-Karp algorithm).

    Args:
        cost_matrix: A 2D list/array of shape (n, n) where cost_matrix[i][j]
                     is the cost of travelling from node i to node j.
                     Use INF for impossible / constraint-violating edges.
    """

    def __init__(self, cost_matrix: list):
        self.n = len(cost_matrix)
        self.cost = cost_matrix
        # dp[mask][i] = min cost to visit the subset of nodes encoded by `mask`,
        # ending at node i (depot is node 0, implicitly excluded from mask)
        self._dp = {}
        # parent[mask][i] = previous node j that led to state (mask, i)
        self._parent = {}

    def solve(self, start: int = 0) -> tuple:
        """
        Solve TSP starting and ending at `start`.

        Returns:
            (total_cost, path)
            total_cost: float — minimum cost of the complete tour
            path: list[int] — ordered node indices (starts and ends at `start`)
                  Returns (INF, []) if no feasible tour exists.
        """
        n = self.n
        if n == 1:
            return 0.0, [start]
        if n == 0:
            return 0.0, []

        # Remap: treat `start` as index 0 internally for cleaner bitmask handling
        # Build a list of all indices excluding start
        others = [i for i in range(n) if i != start]
        # Internal indexing: 0 = depot (start), 1..n-1 = others in original order
        # We keep original indices throughout; mask bit k corresponds to others[k]

        m = len(others)  # number of stops excluding depot
        FULL = (1 << m) - 1

        # dp[(mask, last_idx)] = min cost reaching `last_idx` having visited mask
        # `last_idx` is an index into `others` (0-based within others list)
        dp = {}
        parent = {}

        # Initialise: go from depot directly to each stop
        for k, node in enumerate(others):
            c = self.cost[start][node]
            dp[(1 << k, k)] = c
            parent[(1 << k, k)] = -1  # came from depot

        # Fill DP table
        for mask in range(1, FULL + 1):
            for last_k in range(m):
                if not (mask & (1 << last_k)):
                    continue  # last_k not in visited set
                curr_cost = dp.get((mask, last_k), INF)
                if curr_cost == INF:
                    continue
                last_node = others[last_k]
                # Expand to unvisited stops
                for next_k in range(m):
                    if mask & (1 << next_k):
                        continue  # already visited
                    next_node = others[next_k]
                    edge = self.cost[last_node][next_node]
                    if edge == INF:
                        continue
                    new_cost = curr_cost + edge
                    new_mask = mask | (1 << next_k)
                    key = (new_mask, next_k)
                    if new_cost < dp.get(key, INF):
                        dp[key] = new_cost
                        parent[key] = last_k

        # Find best completion: visit all stops then return to depot
        best_cost = INF
        best_last_k = -1
        for last_k in range(m):
            state = (FULL, last_k)
            if state not in dp:
                continue
            last_node = others[last_k]
            return_cost = self.cost[last_node][start]
            if return_cost == INF:
                continue
            total = dp[state] + return_cost
            if total < best_cost:
                best_cost = total
                best_last_k = last_k

        if best_last_k == -1:
            return INF, []  # No feasible tour

        # Reconstruct path
        path_k = []
        mask = FULL
        last_k = best_last_k
        while last_k != -1:
            path_k.append(last_k)
            prev_k = parent.get((mask, last_k), -1)
            mask = mask ^ (1 << last_k)
            last_k = prev_k

        path_k.reverse()
        # Convert internal stop indices back to original node indices
        path = [start] + [others[k] for k in path_k] + [start]

        return best_cost, path

    def solve_open(self, start: int = 0) -> tuple:
        """
        Solve open TSP: start at `start`, visit all others, do NOT return to start.
        Useful when trucks don't need to return to depot in this planning horizon.

        Returns:
            (total_cost, path) — path does not include return to start
        """
        n = self.n
        if n <= 1:
            return 0.0, [start]

        others = [i for i in range(n) if i != start]
        m = len(others)
        FULL = (1 << m) - 1

        dp = {}
        parent = {}

        for k, node in enumerate(others):
            c = self.cost[start][node]
            dp[(1 << k, k)] = c
            parent[(1 << k, k)] = -1

        for mask in range(1, FULL + 1):
            for last_k in range(m):
                if not (mask & (1 << last_k)):
                    continue
                curr_cost = dp.get((mask, last_k), INF)
                if curr_cost == INF:
                    continue
                last_node = others[last_k]
                for next_k in range(m):
                    if mask & (1 << next_k):
                        continue
                    next_node = others[next_k]
                    edge = self.cost[last_node][next_node]
                    if edge == INF:
                        continue
                    new_cost = curr_cost + edge
                    new_mask = mask | (1 << next_k)
                    key = (new_mask, next_k)
                    if new_cost < dp.get(key, INF):
                        dp[key] = new_cost
                        parent[key] = next_k  # store next_k not last_k

        # Find best end node (no return to depot)
        best_cost = INF
        best_last_k = -1
        for last_k in range(m):
            state = (FULL, last_k)
            total = dp.get(state, INF)
            if total < best_cost:
                best_cost = total
                best_last_k = last_k

        if best_last_k == -1:
            return INF, []

        # Reconstruct
        path_k = []
        mask = FULL
        last_k = best_last_k
        while last_k != -1:
            path_k.append(last_k)
            prev = parent.get((mask, last_k), -1)
            mask = mask ^ (1 << last_k)
            last_k = prev if prev != last_k else -1

        path_k.reverse()
        path = [start] + [others[k] for k in path_k]
        return best_cost, path
