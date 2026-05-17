import os
import sys
import json
from flask import Flask, render_template, request, jsonify

# Ensure src is in path
sys.path.append(os.getcwd())

from src.core.gh_client import GHClient
from src.rcsp.filter import RCSPFilter, RouteCandidate
from src.api.multi_route import multi_route_bp

app = Flask(__name__)
app.register_blueprint(multi_route_bp)

# Initialize Clients
gh_client = GHClient()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/route', methods=['POST'])
def get_route():
    data = request.json
    
    try:
        start_coords = data.get('start') # [lat, lon]
        end_coords = data.get('end')     # [lat, lon]
        
        # Constraints
        height = float(data.get('height', 4.0))
        weight = float(data.get('weight', 20.0))
        length = float(data.get('length', 0.0))
        width = float(data.get('width', 0.0))
        barriers = data.get('barriers', []) 
        
        profile_to_use = data.get('profile', 'truck')
        allowed_profiles = {"truck", "heavy_truck", "hazmat_truck", "long_trailer_truck"}
        if profile_to_use not in allowed_profiles:
            return jsonify({"error": f"Invalid profile '{profile_to_use}'. Available profiles: {sorted(list(allowed_profiles))}"}), 400

        # Default values per profile; includes length/width for long vehicles
        profile_defaults = {
            "truck": (4.0, 20.0, 0.0, 0.0),
            "heavy_truck": (4.5, 40.0, 0.0, 0.0),
            "hazmat_truck": (4.0, 20.0, 0.0, 0.0),
            "long_trailer_truck": (4.75, 44.0, 18.0, 2.6)
        }
        if profile_to_use in profile_defaults:
            dh, dw, dl, dwid = profile_defaults[profile_to_use]
            if height == 0:
                height = dh
            if weight == 0:
                weight = dw
            if length == 0:
                length = dl
            if width == 0:
                width = dwid
        
        truck_specs = {"height": height, "weight": weight, "length": length, "width": width}
        rcsp = RCSPFilter(truck_specs, barriers=barriers)
        
        # 1. Fetch Route from GraphHopper

        # Request details (time/distance are standard)
        route_details = ["time", "distance"] 
        
        gh_response = gh_client.get_route(
            tuple(start_coords), 
            tuple(end_coords), 
            profile=profile_to_use, 
            alternatives=True,
            details=route_details
        )
        
        def is_max_nodes_error(response):
            msg = str(response.get("message", "")).lower()
            if "maximum nodes exceeded" in msg or "max nodes exceeded" in msg:
                return True
            hints = response.get("hints", [])
            if isinstance(hints, list):
                for h in hints:
                    if isinstance(h, dict):
                        details = str(h.get("details", "")).lower()
                        hint_msg = str(h.get("message", "")).lower()
                        if "maximum nodes exceeded" in details or "max nodes exceeded" in details or "maximum nodes exceeded" in hint_msg:
                            return True
            return False

        def is_distance_exceeded(response):
            msg = str(response.get("message", "")).lower()
            if "too far from" in msg:
                return True
            hints = response.get("hints", [])
            if isinstance(hints, list):
                for h in hints:
                    if isinstance(h, dict) and h.get("details", "").endswith("PointDistanceExceededException"):
                        return True
            return False

        if isinstance(gh_response, dict) and is_distance_exceeded(gh_response):
            print("GraphHopper distance exceeded; injecting a midpoint and retrying")
            mid_lat = (start_coords[0] + end_coords[0]) / 2.0
            mid_lon = (start_coords[1] + end_coords[1]) / 2.0
            
            nearest_mid = gh_client.nearest((mid_lat, mid_lon), profile=profile_to_use)
            if nearest_mid and isinstance(nearest_mid, dict) and nearest_mid.get("coordinates"):
                # GH returns [lon, lat] for coordinates
                mid_lon, mid_lat = nearest_mid["coordinates"]
                
            fallback_dist = gh_client.get_route(
                tuple(start_coords),
                tuple(end_coords),
                profile=profile_to_use,
                algo="astar",
                ch_disable=True,
                alternatives=False,
                details=route_details,
                mid_points=[(mid_lat, mid_lon)]
            )
            if fallback_dist and isinstance(fallback_dist, dict) and "paths" in fallback_dist:
                gh_response = fallback_dist

        if isinstance(gh_response, dict) and is_max_nodes_error(gh_response):
            print("GraphHopper max nodes exceeded; retrying with CH-enabled route search")
            fallback = gh_client.get_route(
                tuple(start_coords),
                tuple(end_coords),
                profile=profile_to_use,
                algo="astar",
                ch_disable=False,
                alternatives=False,
                details=route_details
            )
            if fallback and isinstance(fallback, dict) and "paths" in fallback:
                gh_response = fallback
            else:
                fallback2 = gh_client.get_route(
                    tuple(start_coords),
                    tuple(end_coords),
                    profile=profile_to_use,
                    algo="dijkstra",
                    ch_disable=False,
                    alternatives=False,
                    details=route_details
                )
                if fallback2 and isinstance(fallback2, dict) and "paths" in fallback2:
                    gh_response = fallback2
                else:
                    # Continue with original error response if retries fail
                    pass

        if not gh_response:
             # Try to see if it was a profile issue by falling back or just error out
             return jsonify({"error": "Failed to fetch route from GraphHopper (Check if server is running and map covers area)"}), 500

        if "message" in gh_response:
            # Detect PointNotFoundException and try to auto-snap (if nearest <= threshold)
            hints = gh_response.get("hints", [])
            suggestions = []
            point_not_found_indices = []

            if isinstance(hints, list):
                for h in hints:
                    if isinstance(h, dict) and h.get("details", "").endswith(("PointNotFoundException", "PointDistanceExceededException")):
                        idx = h.get("point_index")
                        if idx is not None:
                            point_not_found_indices.append(idx)

            # Configure snap threshold (meters)
            SNAP_THRESHOLD_M = float(data.get('snap_threshold_m', 200.0))
            auto_snaps = {}

            # Collect nearest suggestions and decide whether to auto-snap
            for idx in point_not_found_indices:
                orig_point = tuple(start_coords) if idx == 0 else tuple(end_coords) if idx == 1 else None
                if not orig_point:
                    continue

                nearest_info = gh_client.nearest(orig_point, profile=profile_to_use)

                # If nearest returned a usable distance and coordinates, record suggestion
                if isinstance(nearest_info, dict) and nearest_info.get('coordinates'):
                    # GH nearest gives [lon, lat]
                    coords = nearest_info.get('coordinates')
                    distance = nearest_info.get('distance')
                    suggestions.append({
                        "point_index": idx,
                        "requested": orig_point,
                        "nearest": nearest_info
                    })

                    # Auto-snap if within threshold and distance present
                    if distance is not None and distance <= SNAP_THRESHOLD_M:
                        snapped_latlon = (coords[1], coords[0])
                        auto_snaps[idx] = {"requested": orig_point, "snapped": snapped_latlon, "distance_m": distance}

            # If we have auto-snaps, retry the route with snapped coordinates
            if auto_snaps:
                new_start = auto_snaps.get(0, {}).get('snapped', start_coords)
                new_end = auto_snaps.get(1, {}).get('snapped', end_coords)

                retry_resp = gh_client.get_route(tuple(new_start), tuple(new_end), profile=profile_to_use, alternatives=True, details=route_details)
                if retry_resp and 'paths' in retry_resp:
                    # Use the retried successful response and continue processing below
                    gh_response = retry_resp
                    start_coords = new_start
                    end_coords = new_end
                    applied_auto_snaps = auto_snaps
                else:
                    # Retry failed — return original GH error + suggestions
                    payload = {"error": f"GraphHopper Error: {gh_response['message']}"}
                    if suggestions:
                        payload["suggestions"] = suggestions
                    return jsonify(payload), 400

            # No auto-snap or retry unsuccessful -> return actionable suggestions
            if not auto_snaps:
                payload = {"error": f"GraphHopper Error: {gh_response['message']}"}
                if suggestions:
                    payload["suggestions"] = suggestions
                return jsonify(payload), 400

        if "paths" not in gh_response:
            return jsonify({"error": "No paths found in response"}), 404

        candidates = []
        
        # Process each path returned (usually 1 unless alternatives=True)
        for path in gh_response["paths"]:
            # RouteCandidate expects the raw path json and some meta
            candidate = RouteCandidate(path, query_meta={"tag": "Main Route", "algo": "dijkstra"})
            
            # 2. Evaluate with RCSP
            rcsp.evaluate_route(candidate)
            
            # Serialize
            candidates.append({
                "geometry": candidate.geometry,
                "metrics": candidate.metrics,
                "valid": candidate.is_valid,
                "reason": candidate.rejection_reason,
                "tag": "GraphHopper Route"
            })
            
        resp_payload = {
            "source": f"{start_coords}",
            "destination": f"{end_coords}",
            "candidates": candidates
        }

        # Include auto-snap metadata if applied
        if 'applied_auto_snaps' in locals() and applied_auto_snaps:
            resp_payload["auto_snapped"] = True
            resp_payload["snapped_points"] = applied_auto_snaps

        return jsonify(resp_payload)

    except Exception as e:
        print(f"Error processing route: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
