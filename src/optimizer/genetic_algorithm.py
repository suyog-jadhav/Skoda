"""
Genetic Algorithm + 2-opt — TSP Solver
----------------------------------------
Evolutionary metaheuristic with local search polish.
Excellent for multi-objective scenarios and barrier-heavy graphs.

Usage:
    solver = GeneticAlgorithmTSP(cost_matrix)
    total_cost, path = solver.solve(start=0)
"""

import random
import time

INF = float('inf')


class GeneticAlgorithmTSP:
    """
    Genetic Algorithm with 2-opt local search for TSP.

    Args:
        cost_matrix:     N×N list of floats.
        population_size: number of candidate routes (default 50).
        generations:     max generations (default 50).
        mutation_rate:   probability of mutation per child (default 0.3).
        tournament_k:    tournament selection size (default 5).
    """

    def __init__(
        self,
        cost_matrix: list,
        population_size: int = 50,
        generations: int = 50,
        mutation_rate: float = 0.3,
        tournament_k: int = 5,
    ):
        self.cost = cost_matrix
        self.n = len(cost_matrix)
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.tournament_k = tournament_k

    # ── Tour utilities ────────────────────────────────────────────────

    def _tour_cost(self, tour: list) -> float:
        total = 0.0
        for k in range(len(tour) - 1):
            c = self.cost[tour[k]][tour[k + 1]]
            if c == INF:
                return INF
            total += c
        return total

    def _random_tour(self, start: int, others: list) -> list:
        shuffled = others[:]
        random.shuffle(shuffled)
        return [start] + shuffled + [start]

    # ── Genetic operators ─────────────────────────────────────────────

    def _tournament_select(self, population: list, fitnesses: list) -> list:
        """Tournament selection — pick best of k random individuals."""
        candidates = random.sample(range(len(population)), min(self.tournament_k, len(population)))
        best = max(candidates, key=lambda i: fitnesses[i])
        return population[best][:]

    def _order_crossover(self, p1: list, p2: list, start: int) -> list:
        """
        Order Crossover (OX) on the stop segment (excludes depot at ends).
        Preserves relative order from p2 for nodes not in the cut segment.
        """
        # Work on inner sequence only (strip depot bookends)
        inner1 = p1[1:-1]
        inner2 = p2[1:-1]
        m = len(inner1)

        if m == 0:
            return p1[:]
        if m == 1:
            return p1[:]

        cx1, cx2 = sorted(random.sample(range(m), 2))
        segment = inner1[cx1:cx2]
        remaining = [x for x in inner2 if x not in segment]
        child_inner = remaining[:cx1] + segment + remaining[cx1:]
        return [start] + child_inner + [start]

    def _mutate(self, tour: list) -> list:
        """Randomly swap or insert a stop in the tour."""
        inner = tour[1:-1]
        if len(inner) < 2:
            return tour
        m = random.choice(['swap', 'insert'])
        i, j = random.sample(range(len(inner)), 2)
        if m == 'swap':
            inner[i], inner[j] = inner[j], inner[i]
        else:
            node = inner.pop(i)
            inner.insert(j, node)
        return [tour[0]] + inner + [tour[0]]

    # ── 2-opt local search ────────────────────────────────────────────

    def _two_opt(self, tour: list, max_passes: int = 10) -> list:
        """Repeatedly reverse sub-segments if it reduces cost."""
        best = tour[:]
        best_cost = self._tour_cost(best)
        improved = True
        passes = 0

        while improved and passes < max_passes:
            improved = False
            passes += 1
            for i in range(1, len(best) - 2):
                for j in range(i + 1, len(best) - 1):
                    candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                    c = self._tour_cost(candidate)
                    if c < best_cost:
                        best = candidate
                        best_cost = c
                        improved = True
                        break
                if improved:
                    break

        return best

    # ── Main solver ───────────────────────────────────────────────────

    def solve(self, start: int = 0) -> tuple:
        """
        Run GA + 2-opt.

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

        # ── 1. Initialise population ──────────────────────────────────
        population = [self._random_tour(start, others) for _ in range(self.population_size)]

        best_tour = []
        best_cost = INF
        stagnation = 0

        for gen in range(self.generations):
            costs = [self._tour_cost(ind) for ind in population]
            fitnesses = [1.0 / (c + 1e-9) if c != INF else 0.0 for c in costs]

            # Track global best
            gen_best_idx = min(range(len(costs)), key=lambda i: costs[i])
            if costs[gen_best_idx] < best_cost:
                best_cost = costs[gen_best_idx]
                best_tour = population[gen_best_idx][:]
                stagnation = 0
            else:
                stagnation += 1

            if stagnation >= 15:
                break

            # ── 2. Build next generation ──────────────────────────────
            next_pop = [best_tour[:]]  # Elitism

            while len(next_pop) < self.population_size:
                p1 = self._tournament_select(population, fitnesses)
                p2 = self._tournament_select(population, fitnesses)
                child = self._order_crossover(p1, p2, start)
                if random.random() < self.mutation_rate:
                    child = self._mutate(child)
                next_pop.append(child)

            population = next_pop

        # ── 3. Final 2-opt polish on best ─────────────────────────────
        best_tour = self._two_opt(best_tour, max_passes=20)
        best_cost = self._tour_cost(best_tour)

        return best_cost, best_tour
