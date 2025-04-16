import hashlib
from flask import Flask, json, request, jsonify
from flask_cors import CORS  # For cross-origin support
from flask_caching import Cache

from pyrosm import OSM
import geopandas as gpd
from shapely.ops import unary_union
import os
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)  # Enable CORS for cross-domain requests


# Configuration
load_dotenv()
PBF_PATH = os.environ.get("OSM_DATA_PATH")  # Use environment variable for path
# Load OSM data once at startup
print(PBF_PATH)
osm_parser = OSM(PBF_PATH)  # Parses the PBF file on initialization

app.config.update({
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_URL": os.environ.get("REDIS_URL"),
    "CACHE_DEFAULT_TIMEOUT": 2592000  # 30 days in seconds
})

cache = Cache(app)

def get_osm_parser():
    """Returns the pre-initialized OSM parser."""
    return osm_parser

def make_request_body_cache_key(*args, **kwargs):
    try:
        json_data = request.get_json()
        if not json_data:
            return request.path 
            
        payload_str = json.dumps(json_data, sort_keys=True) 
        
        payload_hash = hashlib.md5(payload_str.encode('utf-8')).hexdigest()
        
        cache_key = f"{request.path}:{payload_hash}"
        return cache_key
    except Exception:
        return request.path
    

@app.route('/v1/find-room', methods=['POST'])
@cache.cached(make_cache_key=make_request_body_cache_key)
def handle_find_room():
    """Endpoint for finding rooms within buildings"""
    try:
        # Validate request payload
        data = request.get_json()
        if not data or 'building' not in data or 'room' not in data:
            return jsonify({"error": "Missing required parameters"}), 400

        # Process request
        result = find_room(
            building_name=data['building'],
            room_identifier=data['room'],
            pbf_path=PBF_PATH
        )
        
        # Handle errors from core logic
        if 'error' in result:
            return jsonify(result), 404
            
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

def find_room(building_name: str, room_identifier: str, pbf_path: str) -> dict:
    """Find a room within a specific building and return its nodes."""
    # Initialize OSM parser
    osm = get_osm_parser()

    buildings = osm.get_buildings(
        custom_filter={
            "name": [building_name]
        })
    
    if buildings.empty:
        return {"error": f"Building '{building_name}' not found"}
    
    # Convert building to single geometry
    building_geom = unary_union(buildings.geometry)
    
    # 2. Find all potential rooms
    room_identifier = room_identifier.upper()
    rooms = osm.get_data_by_custom_criteria(
        custom_filter={
            "indoor": ["room"],
            "ref": [room_identifier],
            "name": [room_identifier]
        },
        extra_attributes=["level"],
        filter_type="keep",
        keep_nodes=True,
        keep_ways=True
    )
    
    if rooms.empty:
        return {"error": f"Room '{room_identifier}' not found in dataset"}
    
    
    # 3. Spatial query to find rooms within building
    rooms["centroid"] = rooms.geometry.apply(
        lambda g: g.centroid if g.geom_type in ["Polygon", "MultiPolygon"] else g
    )
    
    centroids = gpd.GeoDataFrame(rooms, geometry="centroid", crs=4326)
    
    building_gdf = gpd.GeoDataFrame(
        geometry=[building_geom], 
        crs=4326
    )
    
    rooms_in_building = gpd.sjoin(
        centroids, 
        building_gdf, 
        predicate="within", 
        how="inner"
    )
    
    if rooms_in_building.empty:
        return {"error": f"Room '{room_identifier}' not found in {building_name}"}
    
    # 4. Format results with nodes and their coordinates
    results = []
    for _, row in rooms_in_building.iterrows():
        room_nodes = []
        
        # Extract nodes if the geometry is a Polygon or MultiPolygon
        if row.geometry.geom_type == "Polygon":
            room_nodes = list(row.geometry.exterior.coords)
        elif row.geometry.geom_type == "MultiPolygon":
            for poly in row.geometry.geoms:
                room_nodes.extend(list(poly.exterior.coords))
        
        results.append({
            "latitude": row.geometry.centroid.y,
            "longitude": row.geometry.centroid.x,
            "osm_id": row.id,
            "tags": {
                "name": row.get("name"),
                "ref": row.get("ref"),
                "level": row.get("level")
            },
            "nodes": [{"latitude": coord[1], "longitude": coord[0]} for coord in room_nodes]
        })
    
    # Filter exact matches based on ref or name tags
    exact_matches = [
        r for r in results 
        if str(r['tags'].get('ref')) == room_identifier 
        or str(r['tags'].get('name')) == room_identifier
    ]
    
    if not exact_matches:
        return {"error": f"Exact match for '{room_identifier}' not found"}

    return exact_matches[0]  # Return first exact match with nodes included

@app.route('/v1/rooms', methods=['GET'])
@cache.cached(query_string=True)
def handle_rooms():
    osm = get_osm_parser()

    buildings = osm.get_data_by_custom_criteria(
        custom_filter={
            "building": ["university"]
        },
    )
    results = []
    for _, row in buildings.iterrows():
        results.append({
            "osm_id": row.get("osm_id"),
            "name": row.get("name"),
        })
    return jsonify(results)


@app.route('/v1/cache-test')
@cache.cached(timeout=60)
def cache_test():
    return jsonify({"message": "This response is cached for 60 seconds"})

@app.route('/v1/clear-cache', methods=['POST'])
def clear_cache():
    cache.clear() 
    return jsonify({"message": "Cache cleared successfully"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)