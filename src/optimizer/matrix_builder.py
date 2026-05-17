"""
Matrix Builder Module
----------------------
Builds a full cost matrix over all depots + delivery stops.

Strategy:
    1. Try GraphHopper /matrix API (fast, single request).
    2. If /matrix unavailable or fails, fall back to pairwise /route calls.

Cost formula per edge:
    cost = dist_weight × dist_km + time_weight × time_h + fuel_weight × fuel_L

Constraint violations (RCSP barriers) are applied by setting edge cost = INF.
"""

import math
import time

INF = float('inf')

# Default economic weights — can be overridden via cost_weights param
DEFAULT_WEIGHTS = {
    'distance': 1.0,   # per km
    'time': 20.0,      # per hour (value of driver time)
    'fuel': 1.5,       # per litre
}

# Fuel estimate: 30L/100km base
FUEL_L_PER_KM = 0.30


def _compute_edge_cost(dist_m: float, time_ms: float, weights: dict) -> float:
    """Convert raw GH route metrics to an economic cost scalar."""
    if dist_m is None or time_ms is None:
        return INF
    dist_km = dist_m / 1000.0
    time_h = time_ms / 3_600_000.0
    fuel_l_per_km = weights.get('fuel_l_per_km', FUEL_L_PER_KM)
    fuel_L = dist_km * fuel_l_per_km + time_h * 2.0  # idling overhead
    cost = (
        weights.get('distance', 1.0) * dist_km
        + weights.get('time', 20.0) * time_h
        + weights.get('fuel', 1.5) * fuel_L
    )
    return round(cost, 4)


def _try_matrix_api(gh_client, points: list, profile: str) -> dict | None:
    """
    Attempt to call GraphHopper /matrix API.

    Args:
        gh_client: GHClient instance
        points: list of (lat, lon) tuples
        profile: GH vehicle profile string

    Returns:
        dict with 'distances' and 'times' 2D lists (in metres / milliseconds),
        or None if the Matrix API is unavailable.
    """
    try:
        import requests
        url = f"{gh_client.base_url}/matrix"
        point_strings = [f"{lat},{lon}" for lat, lon in points]
        params = {
            'point': point_strings,
            'profile': profile,
            'out_array': ['distances', 'times'],
        }
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if 'distances' in data and 'times' in data:
                return data
        return None
    except Exception as e:
        print(f"[MatrixBuilder] Matrix API failed: {e}")
        return None


def build_cost_matrix(
    gh_client,
    points: list,
    profile: str = 'truck',
    cost_weights: dict = None,
    barriers: list = None,
) -> list:
    """
    Build an N×N cost matrix for all provided points.

    Args:
        gh_client: GHClient instance
        points: list of (lat, lon) tuples. Ordering: depots first, then stops.
        profile: GraphHopper vehicle profile
        cost_weights: dict with keys 'distance', 'time', 'fuel'
        barriers: list of barrier dicts {lat, lon, radius} for INF flagging

    Returns:
        N×N list of floats (cost scalars). INF where unreachable/invalid.
    """
    weights = cost_weights or DEFAULT_WEIGHTS
    n = len(points)
    matrix = [[INF] * n for _ in range(n)]

    for i in range(n):
        matrix[i][i] = 0.0

    # --- Attempt Matrix API ---
    matrix_data = _try_matrix_api(gh_client, points, profile)

    if matrix_data:
        print(f"[MatrixBuilder] Using GH Matrix API for {n}×{n} matrix")
        distances = matrix_data['distances']
        times = matrix_data['times']
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                dist_m = distances[i][j] if distances[i][j] is not None else None
                time_ms = times[i][j] if times[i][j] is not None else None
                if dist_m is None or dist_m == 0 and i != j:
                    matrix[i][j] = INF
                else:
                    matrix[i][j] = _compute_edge_cost(dist_m, time_ms, weights)
    else:
        # --- Fallback: pairwise /route calls ---
        print(f"[MatrixBuilder] Matrix API unavailable — using pairwise routing ({n*(n-1)} calls)")
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                resp = None
                # Try CH first (works for any distance, fast)
                try:
                    resp = gh_client.get_route(
                        points[i], points[j],
                        profile=profile,
                        algo='dijkstra',
                        ch_disable=False,
                        alternatives=False,
                        details=[]
                    )
                except Exception:
                    pass
                # Fallback: astar with CH disabled
                if not resp or 'paths' not in resp or not resp.get('paths'):
                    try:
                        resp = gh_client.get_route(
                            points[i], points[j],
                            profile=profile,
                            algo='astar',
                            ch_disable=True,
                            alternatives=False,
                            details=[]
                        )
                    except Exception:
                        pass
                if resp and isinstance(resp, dict) and resp.get('paths'):
                    path = resp['paths'][0]
                    dist_m = path.get('distance')
                    time_ms = path.get('time')
                    if dist_m:
                        matrix[i][j] = _compute_edge_cost(dist_m, time_ms, weights)
                    else:
                        matrix[i][j] = INF
                else:
                    print(f"[MatrixBuilder] Route {i}→{j} unreachable")
                    matrix[i][j] = INF

    # --- Apply barrier penalties ---
    if barriers:
        matrix = _apply_barrier_penalties(matrix, points, barriers)

    return matrix


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Approximate great-circle distance in metres between two points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _apply_barrier_penalties(matrix: list, points: list, barriers: list) -> list:
    """
    Set matrix[i][j] = INF if the straight-line midpoint of edge i→j
    falls within any barrier radius. This is a conservative approximation;
    the full RCSP geometry check happens at route generation time.
    """
    n = len(points)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if matrix[i][j] == INF:
                continue
            mid_lat = (points[i][0] + points[j][0]) / 2
            mid_lon = (points[i][1] + points[j][1]) / 2
            for b in barriers:
                d = _haversine_m(mid_lat, mid_lon, b['lat'], b['lon'])
                if d <= b.get('radius', 5000):
                    matrix[i][j] = INF
                    break
    return matrix


def edge_metrics(
    gh_client,
    from_point: tuple,
    to_point: tuple,
    profile: str,
    details: list = None,
    cost_weights: dict = None,
) -> dict:
    """
    Fetch detailed edge metrics for a single route leg.
    Tries CH-based routing first, falls back to flexible astar.
    """
    if details is None:
        details = ['max_height', 'max_weight', 'max_length', 'max_width', 'time', 'distance']

    resp = None
    # Try CH (reliable for long-distance India routes)
    try:
        resp = gh_client.get_route(
            from_point, to_point,
            profile=profile,
            algo='dijkstra',
            ch_disable=False,
            alternatives=False,
            details=details
        )
    except Exception:
        pass

    # Fallback to flexible astar
    if not resp or 'paths' not in resp or not resp.get('paths'):
        try:
            resp = gh_client.get_route(
                from_point, to_point,
                profile=profile,
                algo='astar',
                ch_disable=True,
                alternatives=False,
                details=details
            )
        except Exception:
            pass

    if not resp or 'paths' not in resp or not resp['paths']:
        return {'dist_km': None, 'time_h': None, 'fuel_L': None, 'geometry': [], 'raw_path': None}

    path = resp['paths'][0]
    dist_km = path.get('distance', 0) / 1000.0
    time_h = path.get('time', 0) / 3_600_000.0
    fuel_l_per_km = (cost_weights or {}).get('fuel_l_per_km', FUEL_L_PER_KM)
    fuel_L = dist_km * fuel_l_per_km + time_h * 2.0
    geometry = path.get('points', {}).get('coordinates', [])

    return {
        'dist_km': round(dist_km, 3),
        'time_h':  round(time_h, 3),
        'fuel_L':  round(fuel_L, 3),
        'geometry': geometry,
        'raw_path': path,
    }
