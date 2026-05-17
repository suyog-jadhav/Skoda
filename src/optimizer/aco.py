"""
Ant Colony Optimization — TSP Solver
--------------------------------------
Near-optimal TSP solver using pheromone-based probabilistic search.
Excellent for barrier-heavy scenarios because pheromones on blocked
edges are initialised to near-zero, naturally steering ants away.

Usage:
    solver = AntColony(cost_matrix)
    total_cost, path = solver.solve(start=0)
"""

import random
import math
import time

INF = float('inf')


class AntColony:
    """
    Ant Colony Optimization for TSP.

    Args:
        cost_matrix: N×N list of floats. INF = impassable edge.
        n_ants:      number of ants per iteration (default 20).
        iterations:  max iterations (default 100).
        alpha:       pheromone influence exponent (default 1.0).
        beta:        heuristic (1/cost) influence exponent (default 2.0).
        rho:         pheromone evaporation rate (default 0.95).
        Q:           pheromone deposit constant (default 100.0).
    """

    def __init__(
        self,
        cost_matrix: list,
        n_ants: int = 20,
        iterations: int = 100,
        alpha: float = 1.0,
        beta: float = 2.0,
        rho: float = 0.95,
        Q: float = 100.0,
    ):
        self.cost = cost_matrix
        self.n = len(cost_matrix)
        self.n_ants = n_ants
        self.iterations = iterations
        self.alpha = alpha
        self.beta = beta
        self.rho = rho
        self.Q = Q

        # Initialise pheromone matrix — INF edges get near-zero pheromone
        self.tau = []
        for i in range(self.n):
            row = []
            for j in range(self.n):
                if cost_matrix[i][j] == INF or cost_matrix[i][j] == 0:
                    row.append(0.0001)
                else:
                    row.append(1.0 / self.n)
            self.tau.append(row)

    def _heuristic(self, i: int, j: int) -> float:
        c = self.cost[i][j]
        if c == INF or c == 0:
            return 0.0001
        return 1.0 / c

    def _construct_tour(self, start: int) -> list:
        """One ant builds a complete tour from `start`."""
        visited = [False] * self.n
        visited[start] = True
        tour = [start]
        current = start

        for _ in range(self.n - 1):
            # Compute selection probabilities for unvisited nodes
            numerators = []
            candidates = []
            for j in range(self.n):
                if visited[j]:
                    continue
                tau_ij = self.tau[current][j] ** self.alpha
                eta_ij = self._heuristic(current, j) ** self.beta
                numerators.append(tau_ij * eta_ij)
                candidates.append(j)

            if not candidates:
                break

            total = sum(numerators)
            if total == 0:
                # All edges blocked — pick random
                nxt = random.choice(candidates)
            else:
                probs = [v / total for v in numerators]
                # Roulette wheel selection
                r = random.random()
                cumulative = 0.0
                nxt = candidates[-1]
                for idx, p in enumerate(probs):
                    cumulative += p
                    if r <= cumulative:
                        nxt = candidates[idx]
                        break

            tour.append(nxt)
            visited[nxt] = True
            current = nxt

        tour.append(start)  # return to depot
        return tour

    def _tour_cost(self, tour: list) -> float:
        total = 0.0
        for k in range(len(tour) - 1):
            c = self.cost[tour[k]][tour[k + 1]]
            if c == INF:
                return INF
            total += c
        return total

    def _update_pheromones(self, all_tours: list, all_costs: list):
        """Evaporate then deposit."""
        # Evaporation
        for i in range(self.n):
            for j in range(self.n):
                self.tau[i][j] *= self.rho
                if self.tau[i][j] < 0.0001:
                    self.tau[i][j] = 0.0001

        # Deposit
        for tour, cost in zip(all_tours, all_costs):
            if cost == INF:
                continue
            delta = self.Q / cost
            for k in range(len(tour) - 1):
                i, j = tour[k], tour[k + 1]
                self.tau[i][j] += delta
                self.tau[j][i] += delta  # symmetric

    def solve(self, start: int = 0) -> tuple:
        """
        Run ACO and return the best tour found.

        Returns:
            (total_cost, path) — path starts and ends at `start`.
        """
        if self.n <= 1:
            return 0.0, [start]
        if self.n == 2:
            other = 1 - start
            c = self.cost[start][other] + self.cost[other][start]
            return c, [start, other, start]

        t0 = time.time()
        best_cost = INF
        best_tour = []
        stagnation = 0

        for iteration in range(self.iterations):
            tours = [self._construct_tour(start) for _ in range(self.n_ants)]
            costs = [self._tour_cost(t) for t in tours]
            self._update_pheromones(tours, costs)

            iter_best_cost = min(costs)
            iter_best_tour = tours[costs.index(iter_best_cost)]

            if iter_best_cost < best_cost:
                best_cost = iter_best_cost
                best_tour = iter_best_tour[:]
                stagnation = 0
            else:
                stagnation += 1

            # Early stop after 20 iterations without improvement
            if stagnation >= 20:
                break

        return best_cost, best_tour
