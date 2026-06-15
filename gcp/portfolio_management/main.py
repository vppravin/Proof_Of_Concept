import os
from flask import Flask, request, jsonify
from google.cloud import discoveryengine_v1 as discoveryengine

app = Flask(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "gbu-demo-playground")
LOCATION = os.getenv("LOCATION", "global")
DATA_STORE_ID = os.getenv("DATA_STORE_ID", "client-portfolio_1772099480339")

@app.route('/query', methods=['POST'])
def handle_query():
    try:
        user_input = request.json.get("query")
        if not user_input:
            return jsonify({"error": "No query provided"}), 400

we        client = discoveryengine.SearchServiceClient()
        
        # Use search instead of answer_query
        serving_config = client.serving_config_path(
            project=PROJECT_ID,
            location=LOCATION,
            data_store=DATA_STORE_ID,
            serving_config="default_config"
        )
        
        search_request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=user_input,
            page_size=10
        )
        
        response = client.search(request=search_request)
        
        # Extract results
        results = []
        for result in response.results:
            if result.document.struct_data:
                results.append(dict(result.document.struct_data))
        
        return jsonify({
            "results": results,
            "query": user_input,
            "count": len(results)
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
