import math

class RouteCandidate:
    def __init__(self, raw_path_json, query_meta):
        self.raw = raw_path_json
        self.geometry = raw_path_json.get("points", {}).get("coordinates", [])
        self.distance_m = raw_path_json.get("distance", 0)
        self.time_ms = raw_path_json.get("time", 0)
        self.details = raw_path_json.get("details", {})
        self.query_meta = query_meta
        self.is_valid = True
        self.rejection_reason = None
        self.score = 0
        self.metrics = {}

    def get_aggregated_detail(self, key, default=None):
        """
        Helper to extract min/max/sum of details along the path.
        Details are given as [start_index, end_index, value].
        """
        values = []
        detail_list = self.details.get(key, [])
        for item in detail_list:
            # item is [from, to, value]
            val = item[2]
            values.append(val)
        return values

class RCSPFilter:
    def __init__(self, truck_config, barriers=None):
        self.max_height = truck_config.get("height", 4.0) # meters
        self.max_weight = truck_config.get("weight", 20.0) # tons
        # new constraints for long vehicles
        self.max_length = truck_config.get("length", None)  # meters, None means ignore
        self.max_width = truck_config.get("width", None)    # meters
        self.barriers = barriers or [] # List of {lat, lon, radius_m}
        self.fuel_l_per_km = truck_config.get("fuel_l_per_km", 0.30)  # user-supplied efficiency
        self.cost_weights = {
            "distance": 1.0, # per km
            "time": 20.0,    # per hour (value of time)
            "fuel": 1.5,     # per liter
            "toll": 1.0      # per currency unit
        }

    def _dist_sq(self, p1, p2):
        # Approximated Euclidean distance for speed (lat/lon degrees)
        # 1 deg lat ~ 111km. 
        # Using simple euclidean on lat/lon is not accurate for large distances but okay for small barriers check if calibrated.
        # Better: use Haversine or simple projection.
        # Let's use a simple conversion factor for meters.
        # lat_deg_m = 111000
        # lon_deg_m = 111000 * cos(lat)
        
        lat1, lon1 = p1
        lat2, lon2 = p2
        
        d_lat = (lat1 - lat2) * 111000
        d_lon = (lon1 - lon2) * 111000 * math.cos(math.radians((lat1+lat2)/2))
        
        return d_lat*d_lat + d_lon*d_lon

    def evaluate_route(self, route: RouteCandidate):
        # 0. CHECK BARRIERS
        if self.barriers:
            # Check every point? Expensive for long routes.
            # Optimization: Check bounding box first? 
            # For demo, checking points is fine.
            for point in route.geometry:
                # point is [lon, lat] usually from GeoJSON, but we need to verify.
                # Earlier we saw GH returns [lon, lat].
                # My _dist_sq expects [lat, lon].
                pt_lat, pt_lon = point[1], point[0]
                
                for b in self.barriers:
                    # b is {lat, lon, radius}
                    dist_sq = self._dist_sq((pt_lat, pt_lon), (b['lat'], b['lon']))
                    if dist_sq < (b['radius'] * b['radius']):
                        route.is_valid = False
                        route.rejection_reason = "Intersects Barrier"
                        return

        # 1. HARD CONSTRAINTS
        
        # Check Height
        path_heights = route.get_aggregated_detail("max_height")
        for h in path_heights:
            # Some OSM data might be missing, assume valid if None/Unknown
            if h is not None and h < self.max_height:
                route.is_valid = False
                route.rejection_reason = f"Low Clearance: {h}m < {self.max_height}m"
                return

        # Check Weight
        path_weights = route.get_aggregated_detail("max_weight")
        for w in path_weights:
            if w is not None and w < self.max_weight:
                route.is_valid = False
                route.rejection_reason = f"Weight Limit: {w}t < {self.max_weight}t"
                return

        # Check Length (if constraint provided)
        if self.max_length is not None:
            path_lengths = route.get_aggregated_detail("max_length")
            for l in path_lengths:
                if l is not None and l < self.max_length:
                    route.is_valid = False
                    route.rejection_reason = f"Length Limit: {l}m < {self.max_length}m"
                    return

        # Check Width (if constraint provided)
        if self.max_width is not None:
            path_widths = route.get_aggregated_detail("max_width")
            for w in path_widths:
                if w is not None and w < self.max_width:
                    route.is_valid = False
                    route.rejection_reason = f"Width Limit: {w}m < {self.max_width}m"
                    return

        # 2. SOFT CONSTRAINTS / COST CALCULATION
        
        # Distance Cost
        dist_km = route.distance_m / 1000.0
        
        # Time Cost
        time_h = route.time_ms / (1000.0 * 60.0 * 60.0)
        
        # Fuel Estimation using user-supplied efficiency
        fuel_liters = (dist_km * self.fuel_l_per_km) + (time_h * 2.0) # Idling/Traffic overhead
        
        # Total Score
        score = (dist_km * self.cost_weights["distance"]) + \
                (time_h * self.cost_weights["time"]) + \
                (fuel_liters * self.cost_weights["fuel"])

        route.score = score
        route.metrics = {
            "dist_km": round(dist_km, 2),
            "time_h": round(time_h, 2),
            "fuel_L": round(fuel_liters, 2),
            "score": round(score, 2)
        }
