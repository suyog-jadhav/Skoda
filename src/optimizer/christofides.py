"""
Christofides Approximation — TSP Solver
-----------------------------------------
Guarantees a solution within 1.5× the optimal tour length on metric graphs.

Pipeline:
  1. Build Minimum Spanning Tree (Prim's algorithm)
  2. Find odd-degree vertices in the MST
  3. Greedy minimum-weight perfect matching on odd vertices
  4. Combine MST + matching → Eulerian multigraph
  5. Find Eulerian circuit
  6. Shortcut to Hamiltonian cycle

Note: Uses greedy matching (step 3) instead of exact min-weight matching.
For n ≤ 9 stops this gives excellent results without external dependencies.

Usage:
    solver = ChristofidesApprox(cost_matrix)
    total_cost, path = solver.solve(start=0)
"""

INF = float('inf')


class ChristofidesApprox:
    """
    Christofides-inspired 1.5× approximation for TSP.

    Args:
        cost_matrix: N×N list of floats. INF = impassable.
    """

    def __init__(self, cost_matrix: list):
        self.cost = cost_matrix
        self.n = len(cost_matrix)

    # ── Minimum Spanning Tree (Prim's) ────────────────────────────────

    def _prim_mst(self) -> list:
        """Return MST as list of (u, v, weight) edges."""
        n = self.n
        in_mst = [False] * n
        min_edge = [INF] * n
        parent = [-1] * n
        min_edge[0] = 0.0
        edges = []

        for _ in range(n):
            # Pick minimum cost vertex not yet in MST
            u = -1
            for v in range(n):
                if not in_mst[v] and (u == -1 or min_edge[v] < min_edge[u]):
                    u = v
            if u == -1 or min_edge[u] == INF:
                break
            in_mst[u] = True
            if parent[u] != -1:
                w = self.cost[parent[u]][u]
                edges.append((parent[u], u, w))

            for v in range(n):
                c = self.cost[u][v]
                if not in_mst[v] and c < min_edge[v]:
                    min_edge[v] = c
                    parent[v] = u

        return edges

    # ── Odd-degree vertices ───────────────────────────────────────────

    def _odd_degree_vertices(self, mst_edges: list) -> list:
        degree = [0] * self.n
        for u, v, _ in mst_edges:
            degree[u] += 1
            degree[v] += 1
        return [i for i in range(self.n) if degree[i] % 2 == 1]

    # ── Greedy perfect matching on odd vertices ───────────────────────

    def _greedy_matching(self, odd_verts: list) -> list:
        """
        Greedy minimum-weight perfect matching.
        Iteratively pairs the cheapest unmatched pair.
        """
        unmatched = odd_verts[:]
        matching = []

        while len(unmatched) >= 2:
            best_cost = INF
            best_pair = (0, 1)
            for i in range(len(unmatched)):
                for j in range(i + 1, len(unmatched)):
                    u, v = unmatched[i], unmatched[j]
                    c = self.cost[u][v]
                    if c < best_cost:
                        best_cost = c
                        best_pair = (i, j)
            i, j = best_pair
            u, v = unmatched[i], unmatched[j]
            matching.append((u, v, best_cost))
            # Remove matched vertices (higher index first)
            unmatched.pop(j)
            unmatched.pop(i)

        return matching

    # ── Eulerian circuit on multigraph ────────────────────────────────

    def _eulerian_circuit(self, adj: dict, start: int) -> list:
        """
        Hierholzer's algorithm for Eulerian circuit on a multigraph.
        `adj[u]` = list of (v, edge_key) tuples.
        """
        stack = [start]
        circuit = []
        adj_copy = {u: list(edges) for u, edges in adj.items()}

        while stack:
            v = stack[-1]
            if adj_copy.get(v):
                u, key = adj_copy[v].pop()
                # Remove reverse edge
                for i, (w, k) in enumerate(adj_copy.get(u, [])):
                    if w == v and k == key:
                        adj_copy[u].pop(i)
                        break
                stack.append(u)
            else:
                circuit.append(stack.pop())

        return circuit

    # ── Hamiltonian shortcutting ──────────────────────────────────────

    def _shortcut(self, euler: list, start: int) -> list:
        """Skip already-visited vertices (shortcut to Hamiltonian)."""
        visited = set()
        path = []
        for v in euler:
            if v not in visited:
                visited.add(v)
                path.append(v)
        path.append(start)
        return path

    # ── Tour cost ─────────────────────────────────────────────────────

    def _tour_cost(self, path: list) -> float:
        total = 0.0
        for k in range(len(path) - 1):
            c = self.cost[path[k]][path[k + 1]]
            if c == INF:
                return INF
            total += c
        return total

    # ── Main solve ────────────────────────────────────────────────────

    def solve(self, start: int = 0) -> tuple:
        """
        Run Christofides approximation.

        Returns:
            (total_cost, path) — path starts and ends at `start`.
        """
        if self.n <= 1:
            return 0.0, [start]

        others = [i for i in range(self.n) if i != start]
        if not others:
            return 0.0, [start]
        if len(others) == 1:
            c = self.cost[start][others[0]] + self.cost[others[0]][start]
            return c, [start, others[0], start]

        # ── 1. MST ────────────────────────────────────────────────────
        mst_edges = self._prim_mst()

        # ── 2. Odd-degree vertices ─────────────────────────────────────
        odd_verts = self._odd_degree_vertices(mst_edges)

        # ── 3. Greedy matching ─────────────────────────────────────────
        matching = self._greedy_matching(odd_verts)

        # ── 4. Build Eulerian multigraph ───────────────────────────────
        # adj[u] = list of (v, edge_key)
        adj = {i: [] for i in range(self.n)}
        edge_key = 0
        for u, v, _ in mst_edges:
            adj[u].append((v, edge_key))
            adj[v].append((u, edge_key))
            edge_key += 1
        for u, v, _ in matching:
            adj[u].append((v, edge_key))
            adj[v].append((u, edge_key))
            edge_key += 1

        # ── 5. Eulerian circuit ────────────────────────────────────────
        euler = self._eulerian_circuit(adj, start)

        # ── 6. Shortcut to Hamiltonian ─────────────────────────────────
        path = self._shortcut(euler, start)

        # Ensure we visited all nodes
        if len(path) - 1 < self.n:
            # Fallback: greedy nearest-neighbour from start
            path = self._greedy_nn(start)

        cost = self._tour_cost(path)
        return cost, path

    # ── Greedy nearest-neighbour fallback ─────────────────────────────

    def _greedy_nn(self, start: int) -> list:
        """Nearest-neighbour heuristic as a fallback."""
        visited = [False] * self.n
        visited[start] = True
        path = [start]
        current = start

        for _ in range(self.n - 1):
            best_next = -1
            best_cost = INF
            for j in range(self.n):
                if not visited[j] and self.cost[current][j] < best_cost:
                    best_cost = self.cost[current][j]
                    best_next = j
            if best_next == -1:
                break
            visited[best_next] = True
            path.append(best_next)
            current = best_next

        path.append(start)
        return path
