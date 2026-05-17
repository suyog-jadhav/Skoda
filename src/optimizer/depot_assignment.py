"""
Depot Assignment Module
------------------------
Assigns delivery stops to the most suitable depot (A or B) using a
constraint-aware cost scoring strategy.

Strategy:
    1. For each stop, compute the cost from Depot A and Depot B using the
       pre-built cost matrix.
    2. Use INF cost for depot→stop edges that are constraint-violating
       (signalled by the matrix builder).
    3. Assign each stop to the depot with the lower adjusted cost.
    4. If both depots return INF for a stop, it is flagged as unserviceable.

Returns two clusters ready for the Held-Karp TSP solver.
"""

INF = float('inf')


def assign_stops_to_depots(
    cost_matrix: list,
    depot_a_idx: int,
    depot_b_idx: int,
    stop_indices: list,
) -> dict:
    """
    Assign each stop to the depot offering the lowest feasible travel cost.

    Args:
        cost_matrix: Full N×N cost matrix (node ordering: depots first, then stops).
        depot_a_idx: Row/column index of Depot A in cost_matrix.
        depot_b_idx: Row/column index of Depot B in cost_matrix.
        stop_indices: List of row/column indices representing delivery stops.

    Returns:
        dict with keys:
            'depot_a': list of stop indices assigned to Depot A
            'depot_b': list of stop indices assigned to Depot B
            'unserviceable': list of stop indices that cannot be reached from either depot
            'assignment_costs': dict mapping stop_idx -> {'a': float, 'b': float, 'assigned': 'A'|'B'|'NONE'}
    """
    depot_a_stops = []
    depot_b_stops = []
    unserviceable = []
    assignment_costs = {}

    for stop_idx in stop_indices:
        cost_a = cost_matrix[depot_a_idx][stop_idx]
        cost_b = cost_matrix[depot_b_idx][stop_idx]

        record = {'a': cost_a, 'b': cost_b}

        if cost_a == INF and cost_b == INF:
            unserviceable.append(stop_idx)
            record['assigned'] = 'NONE'
        elif cost_a <= cost_b:
            depot_a_stops.append(stop_idx)
            record['assigned'] = 'A'
        else:
            depot_b_stops.append(stop_idx)
            record['assigned'] = 'B'

        assignment_costs[stop_idx] = record

    return {
        'depot_a': depot_a_stops,
        'depot_b': depot_b_stops,
        'unserviceable': unserviceable,
        'assignment_costs': assignment_costs,
    }


def build_cluster_matrix(
    full_matrix: list,
    depot_idx: int,
    stop_indices: list,
) -> tuple:
    """
    Extract a sub-matrix for a specific depot + its assigned stops.

    Node ordering in the returned matrix:
        0 = depot, 1..n = stops in the order they appear in stop_indices

    Args:
        full_matrix: Full N×N cost matrix.
        depot_idx: Index of the depot in the full matrix.
        stop_indices: Ordered list of stop indices assigned to this depot.

    Returns:
        (sub_matrix, index_map)
        sub_matrix: (len(stop_indices)+1) × (len(stop_indices)+1) cost matrix
        index_map: list mapping sub_matrix position -> full_matrix index
                   index_map[0] = depot_idx, index_map[k] = stop_indices[k-1]
    """
    nodes = [depot_idx] + list(stop_indices)
    n = len(nodes)
    sub = [[INF] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                sub[i][j] = 0.0
            else:
                sub[i][j] = full_matrix[nodes[i]][nodes[j]]

    return sub, nodes
