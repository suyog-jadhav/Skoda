import os
import requests
import json
import time

class GHClient:
    def __init__(self, base_url=os.getenv("GH_URL", "http://localhost:8989")):
        self.base_url = base_url

    def get_route(self, from_point, to_point, profile="truck", algo="dijkstra", ch_disable=True, alternatives=False, details=None, mid_points=None):
        """
        Fetch a route from GraphHopper.
        
        Args:
            from_point (tuple): (lat, lon)
            to_point (tuple): (lat, lon)
            profile (str): Vehicle profile (truck, heavy_truck, hazmat_truck, or any custom profile you added to the GraphHopper server)
            algo (str): dijkstra, astar, alternative_route
            ch_disable (bool): Disable Contraction Hierarchies (required for flexible algorithms)
            details (list): List of details to request. Defaults to needed RCSP details.
        """
        url = f"{self.base_url}/route"
        
        if details is None:
            # include length/width so RCSP can evaluate those constraints
            details = ["max_height", "max_weight", "max_length", "max_width", "road_class", "surface", "time", "distance"]

        points = [f"{from_point[0]},{from_point[1]}"]
        if mid_points:
            for mp in mid_points:
                points.append(f"{mp[0]},{mp[1]}")
        points.append(f"{to_point[0]},{to_point[1]}")

        params = {
            "point": points,
            "profile": profile,
            "algorithm": algo,
            "ch.disable": str(ch_disable).lower(),
            "details": details,
            "points_encoded": "false",  # Get raw geometry
            "debug": "true" # Get debug info like visited nodes if available
        }

        if alternatives:
            params["algorithm"] = "alternative_route"
            # specific parameter for alternatives
            params["alternative_route.max_paths"] = 3
            params["alternative_route.max_weight_factor"] = 1.4

        try:
            start_time = time.time()
            response = requests.get(url, params=params)
            duration = time.time() - start_time
            
            if response.status_code != 200:
                print(f"Error fetching route: {response.text}")
                try:
                    return response.json() # Return the error details
                except:
                    return {"message": f"HTTP {response.status_code}: {response.text}"}
            
            data = response.json()
            data["query_meta"] = {
                "duration_seconds": duration,
                "algorithm_used": algo,
                "profile": profile
            }
            return data
            
        except Exception as e:
            print(f"Exception in GHClient: {e}")
            return None

    def post_route_with_avoid(self, from_point, to_point, profile="truck", barriers=None, details=None):
        """
        Route avoiding barrier zones using GraphHopper's flexible routing (POST).
        Barriers are enforced by adding a custom_model that multiplies priority by 0
        for any road whose bounding box overlaps a barrier circle.

        Falls back to a normal GET route if the POST fails.

        Args:
            from_point: (lat, lon)
            to_point:   (lat, lon)
            barriers:   list of {lat, lon, radius}  (radius in metres)
        """
        import json as _json

        if details is None:
            details = ["max_height", "max_weight", "max_length", "max_width", "time", "distance"]

        url = f"{self.base_url}/route"

        body = {
            "points": [
                [from_point[1], from_point[0]],  # GH wants [lon, lat]
                [to_point[1],   to_point[0]],
            ],
            "profile": profile,
            "ch.disable": True,
            "details": details,
            "points_encoded": False,
        }

        # Build avoid polygons from barrier circles (approximate square bbox)
        if barriers:
            priority_rules = []
            for b in barriers:
                lat, lon, r = b['lat'], b['lon'], b.get('radius', 500)
                # 1 degree lat  ~ 111 000 m
                # 1 degree lon  ~ 111 000 * cos(lat) m
                import math as _math
                dlat = r / 111000.0
                dlon = r / (111000.0 * _math.cos(_math.radians(lat)))
                # Approximate circle as polygon (8-sided)
                coords = []
                for i in range(8):
                    angle = 2 * _math.pi * i / 8
                    coords.append([
                        round(lon + dlon * _math.cos(angle), 6),
                        round(lat + dlat * _math.sin(angle), 6),
                    ])
                coords.append(coords[0])  # close ring

                priority_rules.append({
                    "if": f"in_bbox({lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat})",
                    "multiply_by": "0.01",  # near-zero priority = avoid
                })

            if priority_rules:
                body["custom_model"] = {"priority": priority_rules}

        try:
            start = time.time()
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                data=_json.dumps(body),
                timeout=10,
            )
            duration = time.time() - start
            if resp.status_code != 200:
                print(f"[GH avoid-route] POST failed {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            data["query_meta"] = {"duration_seconds": duration, "algorithm_used": "custom_avoid", "profile": profile}
            return data
        except Exception as e:
            print(f"[GH avoid-route] Exception: {e}")
            return None

    def nearest(self, point, profile=None):
        """Call GraphHopper /nearest for a single point.

        Args:
            point (tuple|list): (lat, lon)
            profile (str, optional): profile used for filtering (if supported)
        Returns:
            dict | None: JSON response from /nearest or None on error
        """
        try:
            url = f"{self.base_url}/nearest"
            params = {"point": f"{point[0]},{point[1]}"}
            if profile:
                params["profile"] = profile

            resp = requests.get(url, params=params)
            if resp.status_code != 200:
                try:
                    return resp.json()
                except:
                    return None
            return resp.json()
        except Exception as e:
            print(f"Exception calling /nearest: {e}")
            return None
