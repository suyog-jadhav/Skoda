"""
Multi-Route API Blueprint
--------------------------
Exposes POST /api/multi-route for multi-depot multi-stop route optimization.

Pipeline:
    1. Parse depots, stops, vehicle constraints, barriers
    2. Build cost matrix (GH Matrix API or pairwise fallback)
    3. Assign stops to depots (greedy, cost-aware)
    4. Solve optimal stop order per depot cluster (Held-Karp TSP)
    5. Generate actual road geometries for each leg
    6. Validate each leg via RCSP filter
    7. Return optimized routes, alternatives, rejected legs, analytics
"""

import sys
import os

from flask import Blueprint, request, jsonify

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from src.core.gh_client import GHClient
from src.rcsp.filter import RCSPFilter, RouteCandidate
from src.optimizer.matrix_builder import build_cost_matrix, edge_metrics, DEFAULT_WEIGHTS
from src.optimizer.depot_assignment import assign_stops_to_depots, build_cluster_matrix
from src.optimizer.held_karp import HeldKarp
from src.optimizer.aco import AntColony
from src.optimizer.genetic_algorithm import GeneticAlgorithmTSP
from src.optimizer.christofides import ChristofidesApprox

INF = float('inf')
import math

def sanitize_json(obj):
    """
    Recursively replace float Infinity / NaN with None so that
    Flask's jsonify never emits the invalid JSON token 'Infinity'.
    """
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    return obj

multi_route_bp = Blueprint('multi_route', __name__)
_gh_client = GHClient()

ALLOWED_PROFILES = {'truck', 'heavy_truck', 'hazmat_truck', 'canopy_truck', 'long_trailer_truck'}

PROFILE_DEFAULTS = {
    'truck':              {'height': 4.0,  'weight': 20.0, 'length': 0.0,  'width': 0.0},
    'heavy_truck':        {'height': 4.5,  'weight': 40.0, 'length': 0.0,  'width': 0.0},
    'hazmat_truck':       {'height': 4.0,  'weight': 20.0, 'length': 0.0,  'width': 0.0},
    'canopy_truck':       {'height': 3.5,  'weight': 15.0, 'length': 0.0,  'width': 0.0},
    'long_trailer_truck': {'height': 4.75, 'weight': 44.0, 'length': 18.0, 'width': 2.6},
}


def _resolve_profile_defaults(vehicle_profile: dict) -> dict:
    """Fill missing truck constraint values from profile defaults."""
    profile = vehicle_profile.get('profile', 'truck')
    if profile not in ALLOWED_PROFILES:
        profile = 'truck'
    defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS['truck'])
    return {
        'profile': profile,
        'height': float(vehicle_profile.get('height') or defaults['height']),
        'weight': float(vehicle_profile.get('weight') or defaults['weight']),
        'length': float(vehicle_profile.get('length') or defaults['length']),
        'width':  float(vehicle_profile.get('width')  or defaults['width']),
    }


def _generate_leg(
    gh_client: GHClient,
    from_node: dict,
    to_node: dict,
    profile: str,
    truck_specs: dict,
    barriers: list,
    cost_weights: dict = None,
) -> dict:
    """
    Generate a single route leg from `from_node` to `to_node`, validate via RCSP.

    Returns a leg dict ready for JSON serialisation.
    """
    from_point = (from_node['lat'], from_node['lon'])
    to_point = (to_node['lat'], to_node['lon'])

    metrics = edge_metrics(
        gh_client, from_point, to_point, profile,
        details=['max_height', 'max_weight', 'max_length', 'max_width', 'time', 'distance'],
        cost_weights=cost_weights,
    )

    leg = {
        'from_id':  from_node.get('id', '?'),
        'from_name': from_node.get('name', '?'),
        'to_id':   to_node.get('id', '?'),
        'to_name': to_node.get('name', '?'),
        'geometry': metrics['geometry'],
        'metrics': {
            'dist_km': metrics['dist_km'],
            'time_h':  metrics['time_h'],
            'fuel_L':  metrics['fuel_L'],
        },
        'valid':  False,
        'reason': 'No route found',
    }

    if not metrics['raw_path']:
        return leg

    # RCSP validation — include fuel_l_per_km so filter uses the same rate
    truck_specs_with_fuel = {**truck_specs, 'fuel_l_per_km': (cost_weights or {}).get('fuel_l_per_km', 0.30)}
    rcsp = RCSPFilter(truck_specs_with_fuel, barriers=barriers)
    candidate = RouteCandidate(
        metrics['raw_path'],
        query_meta={'tag': f"{from_node.get('id')}→{to_node.get('id')}", 'algo': 'astar'}
    )
    rcsp.evaluate_route(candidate)

    # ── Barrier rerouting: if blocked, ask GH to avoid the barrier zones ─────
    if not candidate.is_valid and candidate.rejection_reason == 'Intersects Barrier' and barriers:
        print(f'[Reroute] {from_node.get("id")} → {to_node.get("id")} blocked — trying avoid-route')
        avoid_resp = gh_client.post_route_with_avoid(
            from_point, to_point, profile=profile, barriers=barriers,
            details=['max_height', 'max_weight', 'max_length', 'max_width', 'time', 'distance']
        )
        if avoid_resp and 'paths' in avoid_resp and avoid_resp['paths']:
            alt_path = avoid_resp['paths'][0]
            alt_candidate = RouteCandidate(alt_path, query_meta={'tag': 'rerouted', 'algo': 'custom_avoid'})
            rcsp.evaluate_route(alt_candidate)

            if alt_candidate.is_valid:
                # Use the rerouted path
                candidate = alt_candidate
                leg['geometry'] = alt_candidate.geometry
                leg['metrics'] = {
                    'dist_km': alt_candidate.metrics.get('dist_km'),
                    'time_h':  alt_candidate.metrics.get('time_h'),
                    'fuel_L':  alt_candidate.metrics.get('fuel_L'),
                }
                leg['rerouted'] = True
                print(f'[Reroute] ✓ Alternative found for {from_node.get("id")} → {to_node.get("id")}')
            else:
                print(f'[Reroute] ✗ Alternative still blocked: {alt_candidate.rejection_reason}')

    leg['valid'] = candidate.is_valid
    leg['reason'] = candidate.rejection_reason

    # Compute full cost using actual user-supplied weights
    weights = cost_weights or DEFAULT_WEIGHTS
    leg['cost'] = round(
        (leg['metrics'].get('dist_km') or 0) * weights.get('distance', 1.0)
        + (leg['metrics'].get('time_h') or 0) * weights.get('time', 20.0)
        + (leg['metrics'].get('fuel_L') or 0) * weights.get('fuel', 1.5),
        2
    )

    return leg


def _run_algorithm_comparison(sub_matrix: list, start: int = 0) -> dict:
    """
    Run all 4 TSP solvers on the same sub_matrix and return comparison data.
    Each entry: { cost, path, time_ms, label }
    """
    import time

    INF = float('inf')
    results = {}

    solvers = [
        ('held_karp',    lambda: HeldKarp(sub_matrix).solve(start=start)),
        ('christofides', lambda: ChristofidesApprox(sub_matrix).solve(start=start)),
        ('aco',          lambda: AntColony(sub_matrix).solve(start=start)),
        ('genetic',      lambda: GeneticAlgorithmTSP(sub_matrix).solve(start=start)),
    ]

    labels = {
        'held_karp':    'Held-Karp (Exact DP)',
        'christofides': 'Christofides (≤1.5× Optimal)',
        'aco':          'Ant Colony Optimization',
        'genetic':      'Genetic Algorithm + 2-opt',
    }

    for name, fn in solvers:
        t0 = time.time()
        try:
            cost, path = fn()
        except Exception as e:
            print(f'[AlgoCompare] {name} failed: {e}')
            cost, path = INF, []
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        results[name] = {
            'label':     labels[name],
            'cost':      round(cost, 4) if cost != INF else None,
            'path':      path,
            'time_ms':   elapsed_ms,
            'feasible':  cost != INF,
        }

    # Recommendation: feasible solver with lowest cost
    feasible = {k: v for k, v in results.items() if v['feasible']}
    if feasible:
        recommendation = min(feasible, key=lambda k: feasible[k]['cost'])
    else:
        recommendation = 'held_karp'  # fallback

    return results, recommendation


def _solve_depot_cluster(
    gh_client: GHClient,
    depot_node: dict,
    stop_nodes: list,
    full_matrix: list,
    depot_idx: int,
    stop_indices: list,
    profile: str,
    truck_specs: dict,
    barriers: list,
    cost_weights: dict,
) -> dict:
    """
    Run Held-Karp on this depot's cluster and generate geometries.

    Also runs all 4 algorithms for comparison and returns the comparison block.

    Returns a route dict with legs, totals, stop_sequence, and algorithm_comparison.
    """
    if not stop_nodes:
        return {
            'depot': depot_node.get('id', '?'),
            'depot_name': depot_node.get('name', '?'),
            'stop_sequence': [],
            'legs': [],
            'totals': {'dist_km': 0, 'time_h': 0, 'fuel_L': 0, 'cost': 0},
            'all_valid': True,
        }

    # Build cluster sub-matrix
    sub_matrix, index_map = build_cluster_matrix(full_matrix, depot_idx, stop_indices)

    # ── Run all 4 algorithms for comparison ──────────────────────────────────
    comparison, recommendation = _run_algorithm_comparison(sub_matrix, start=0)

    # ── Use Held-Karp path for actual route generation ───────────────────────
    hk_result = comparison['held_karp']
    total_cost = hk_result['cost'] if hk_result['feasible'] else INF
    path = hk_result['path'] if hk_result['path'] else [0]

    # path is [0, s1, s2, ..., sk, 0] in sub_matrix coordinates
    # Convert to original node list (depot_node + stop_nodes)
    all_nodes = [depot_node] + stop_nodes  # parallel to index_map

    # Map sub_matrix indices to actual node dicts
    # index_map[0] = depot_idx (global), index_map[k] = stop_indices[k-1] (global)
    # We need sub_matrix index → node dict
    sub_to_node = {0: depot_node}
    for k, stop_node in enumerate(stop_nodes):
        sub_to_node[k + 1] = stop_node

    # Build legs following the TSP path
    legs = []
    stop_sequence = []

    for step in range(len(path) - 1):
        from_sub_idx = path[step]
        to_sub_idx = path[step + 1]
        from_node = sub_to_node[from_sub_idx]
        to_node = sub_to_node[to_sub_idx]

        # Collect stop IDs (skip depot which is sub index 0)
        if to_sub_idx != 0:
            stop_sequence.append(to_node.get('id', f'stop_{step}'))

        leg = _generate_leg(gh_client, from_node, to_node, profile, truck_specs, barriers, cost_weights)
        legs.append(leg)

    # Totals
    valid_legs = [l for l in legs if l['valid']]
    total_dist = sum((l['metrics'].get('dist_km') or 0) for l in legs)
    total_time = sum((l['metrics'].get('time_h') or 0) for l in legs)
    total_fuel = sum((l['metrics'].get('fuel_L') or 0) for l in legs)
    total_cost_sum = sum((l.get('cost') or 0) for l in legs)

    return {
        'depot': depot_node.get('id', '?'),
        'depot_name': depot_node.get('name', '?'),
        'stop_sequence': stop_sequence,
        'legs': legs,
        'totals': {
            'dist_km': round(total_dist, 2),
            'time_h':  round(total_time, 2),
            'fuel_L':  round(total_fuel, 2),
            'cost':    round(total_cost_sum, 2),
        },
        'all_valid': all(l['valid'] for l in legs),
        'tsp_cost': round(total_cost, 4) if total_cost != INF else None,
        'algorithm_comparison': comparison,
        'recommendation': recommendation,
    }


@multi_route_bp.route('/api/multi-route', methods=['POST'])
def multi_route():
    """
    POST /api/multi-route

    Body (JSON):
    {
        "depots": [
            {"id": "A", "name": "Mumbai Depot", "lat": 19.076, "lon": 72.8777},
            {"id": "B", "name": "Pune Hub",     "lat": 18.5204,"lon": 73.8567}
        ],
        "stops": [
            {"id": "s1", "name": "Nashik", "lat": 19.9975, "lon": 73.7898},
            ...
        ],
        "vehicle_profile": {
            "profile": "truck",
            "height": 4.0, "weight": 20.0, "length": 0.0, "width": 0.0
        },
        "barriers": [{"lat": 19.5, "lon": 74.0, "radius": 5000}],
        "cost_weights": {
            "distance": 2.5,    // ₹ per km  (cost_per_km from UI)
            "fuel": 102.0,      // ₹ per litre (fuel_price from UI)
            "time": 204.0       // ₹ per hour  (fuel_price × 2 L/h idling)
        }
    }
    """
    body = request.json or {}

    depots = body.get('depots', [])
    stops  = body.get('stops', [])
    vehicle_profile = body.get('vehicle_profile', {})
    barriers = body.get('barriers', [])
    cost_weights = body.get('cost_weights', DEFAULT_WEIGHTS)

    # --- Validate inputs ---
    if len(depots) < 1:
        return jsonify({'error': 'At least one depot is required'}), 400
    if len(stops) < 1:
        return jsonify({'error': 'At least one delivery stop is required'}), 400
    if len(stops) > 9:
        return jsonify({'error': 'Maximum 9 delivery stops supported'}), 400

    # Cap to 2 depots
    depots = depots[:2]
    depot_a = depots[0]
    depot_b = depots[1] if len(depots) > 1 else None

    # Resolve profile & constraints
    specs = _resolve_profile_defaults(vehicle_profile)
    profile = specs['profile']
    truck_specs = {k: specs[k] for k in ('height', 'weight', 'length', 'width')}

    try:
        # ── 1. Build node list (depots first, then stops) ──
        nodes = list(depots) + list(stops)
        points = [(n['lat'], n['lon']) for n in nodes]

        depot_a_idx = 0
        depot_b_idx = 1 if depot_b else 0
        stop_indices = list(range(len(depots), len(nodes)))

        # ── 2. Build cost matrix ──
        matrix = build_cost_matrix(
            _gh_client, points, profile=profile,
            cost_weights=cost_weights, barriers=barriers
        )

        # ── 3. Depot assignment ──
        if depot_b:
            assignment = assign_stops_to_depots(matrix, depot_a_idx, depot_b_idx, stop_indices)
        else:
            # Single depot — all stops go to A
            assignment = {
                'depot_a': stop_indices,
                'depot_b': [],
                'unserviceable': [],
                'assignment_costs': {i: {'a': matrix[depot_a_idx][i], 'b': INF, 'assigned': 'A'} for i in stop_indices},
            }

        # ── 4. Build node lookup for quick access ──
        node_by_idx = {i: nodes[i] for i in range(len(nodes))}

        # ── 5. Solve Depot A cluster ──
        a_stop_nodes = [node_by_idx[i] for i in assignment['depot_a']]
        route_a = _solve_depot_cluster(
            _gh_client, depot_a, a_stop_nodes,
            matrix, depot_a_idx, assignment['depot_a'],
            profile, truck_specs, barriers, cost_weights
        )
        route_a['assigned_stops'] = len(assignment['depot_a'])

        optimized_routes = [route_a]

        # ── 6. Solve Depot B cluster (if exists and has stops) ──
        if depot_b and assignment['depot_b']:
            b_stop_nodes = [node_by_idx[i] for i in assignment['depot_b']]
            route_b = _solve_depot_cluster(
                _gh_client, depot_b, b_stop_nodes,
                matrix, depot_b_idx, assignment['depot_b'],
                profile, truck_specs, barriers, cost_weights
            )
            route_b['assigned_stops'] = len(assignment['depot_b'])
            optimized_routes.append(route_b)
        elif depot_b:
            optimized_routes.append({
                'depot': depot_b.get('id', 'B'),
                'depot_name': depot_b.get('name', 'Depot B'),
                'stop_sequence': [],
                'legs': [],
                'totals': {'dist_km': 0, 'time_h': 0, 'fuel_L': 0, 'cost': 0},
                'all_valid': True,
                'assigned_stops': 0,
            })

        # ── 7. Compile analytics ──
        all_legs = [l for r in optimized_routes for l in r.get('legs', [])]
        infeasible_legs = [l for l in all_legs if not l['valid']]
        unserviceable_nodes = [node_by_idx[i] for i in assignment.get('unserviceable', [])]

        analytics = {
            'total_stops': len(stops),
            'depot_a_stops': len(assignment['depot_a']),
            'depot_b_stops': len(assignment['depot_b']),
            'unserviceable_stops': len(assignment.get('unserviceable', [])),
            'total_dist_km': round(sum(r['totals']['dist_km'] for r in optimized_routes), 2),
            'total_time_h':  round(sum(r['totals']['time_h']  for r in optimized_routes), 2),
            'total_fuel_L':  round(sum(r['totals']['fuel_L']  for r in optimized_routes), 2),
            'total_cost':    round(sum(r['totals']['cost']     for r in optimized_routes), 2),
            'total_legs':    len(all_legs),
            'infeasible_legs': len(infeasible_legs),
            'profile_used':  profile,
            'truck_specs':   truck_specs,
            'assignment_costs': {
                str(k): v for k, v in assignment.get('assignment_costs', {}).items()
            },
        }

        rejected_routes = [
            {
                'leg': l,
                'rejection_reason': l['reason'],
            }
            for l in infeasible_legs
        ]

        # Aggregate algorithm_comparison across all depot clusters (use depot A's as primary)
        primary_comparison = optimized_routes[0].get('algorithm_comparison', {})
        primary_recommendation = optimized_routes[0].get('recommendation', 'held_karp')

        return jsonify(sanitize_json({
            'optimized_routes': optimized_routes,
            'alternatives': [],
            'rejected_routes': rejected_routes,
            'unserviceable': [{'id': n['id'], 'name': n['name']} for n in unserviceable_nodes],
            'analytics': analytics,
            'algorithm_comparison': primary_comparison,
            'recommendation': primary_recommendation,
        }))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
