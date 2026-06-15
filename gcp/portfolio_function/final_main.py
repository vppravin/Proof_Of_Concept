import functions_framework
import requests
import google.auth
import google.auth.transport.requests
import logging
from flask import Request, Response
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = "gbu-demo-playground"

# In-memory session storage (use Redis/Firestore for production)
SESSIONS = {}
SESSION_TIMEOUT = timedelta(hours=1)

# Multiple data stores
DATA_STORES = {
    "client-portfolio": "client-portfolio_1772099480339",
    "loginevents": "loginevents_1772444147480",
    "users": "users_1772444782062",
    "productclicks": "productclicks_1772444918030",
    "products": "products_1772445573120"
}

GEMINI_URL = f"https://us-central1-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent"

def get_access_token():
    """Get OAuth2 access token using service account credentials"""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token

@functions_framework.http
def portfolio_query(request: Request):
    """
    Portfolio Query API - Generic data query system using Search + Gemini
    
    Request Body:
        {
            "query": "Your natural language question"
        }
    
    Response:
        {
            "response": "Natural language answer",
            "sessionId": "",
            "dataCount": 4
        }
    """
    
    # Handle CORS preflight
    if request.method == "OPTIONS":
        return Response("", status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600"
        })
    
    try:
        # Parse request
        body = request.get_json(silent=True)
        if not body or "query" not in body:
            return Response(
                json.dumps({"error": "Missing 'query' in request body"}),
                status=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"}
            )

        user_query = body["query"]
        session_id = body.get("sessionId", "")
        
        # Generate or retrieve session
        if not session_id or session_id not in SESSIONS:
            session_id = str(uuid.uuid4())
            SESSIONS[session_id] = {
                "history": [],
                "created": datetime.now(),
                "last_access": datetime.now()
            }
            logger.info(f"New session created: {session_id}")
        else:
            # Update last access time
            SESSIONS[session_id]["last_access"] = datetime.now()
            logger.info(f"Existing session: {session_id}")
        
        # Clean up expired sessions
        expired = [sid for sid, data in SESSIONS.items() 
                   if datetime.now() - data["last_access"] > SESSION_TIMEOUT]
        for sid in expired:
            del SESSIONS[sid]
        
        logger.info(f"User query: {user_query}")

        # Handle greetings and conversational queries
        query_lower = user_query.lower().strip()
        greetings = ["hi", "hello", "hey", "hola", "greetings", "good morning", "good afternoon", "good evening"]
        
        if query_lower in greetings or any(query_lower.startswith(g) for g in greetings):
            return Response(json.dumps({
                "response": "Hello! How can I help you today?",
                "sessionId": "",
                "dataCount": 0
            }), mimetype="application/json", headers={"Access-Control-Allow-Origin": "*"})

        # Smart routing: determine which data stores to query based on keywords
        query_lower = user_query.lower()
        
        # Determine relevant data stores
        relevant_stores = {}
        
        # Client portfolio keywords
        if any(word in query_lower for word in ["client", "portfolio", "income", "salary", "earn", "city", "location"]):
            relevant_stores["client-portfolio"] = DATA_STORES["client-portfolio"]
        
        # User keywords
        if any(word in query_lower for word in ["user", "users", "username", "email", "account", "accounts", "profile", "profiles", "subscriber", "subscription"]):
            relevant_stores["users"] = DATA_STORES["users"]
        
        # Login events keywords
        if any(word in query_lower for word in ["login", "logout", "session", "access", "sign in", "authentication"]):
            relevant_stores["loginevents"] = DATA_STORES["loginevents"]
        
        # Product clicks keywords
        if any(word in query_lower for word in ["click", "clicks", "view", "views", "browse", "interaction", "engagement", "cart", "add to cart", "purchase", "purchased", "buy", "bought"]):
            relevant_stores["productclicks"] = DATA_STORES["productclicks"]
        
        # Products keywords
        if any(word in query_lower for word in ["product", "products", "item", "items", "catalog", "inventory", "price", "prices", "category", "categories", "available", "availability"]):
            relevant_stores["products"] = DATA_STORES["products"]
        
        # If no specific keywords, query all stores
        if not relevant_stores:
            relevant_stores = DATA_STORES.copy()
            logger.info("No specific keywords found, querying all data stores")
        else:
            logger.info(f"Querying relevant stores: {list(relevant_stores.keys())}")

        # Get authentication token
        access_token = get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Step 1: Search across all data stores in parallel
        def search_datastore(ds_name, ds_id):
            """Search a single data store"""
            search_url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/collections/default_collection/dataStores/{ds_id}/servingConfigs/default_search:search"
            try:
                response = requests.post(
                    search_url,
                    headers=headers,
                    json={"query": user_query, "pageSize": 50},
                    timeout=10
                )
                if response.status_code == 200:
                    results = response.json()
                    data = []
                    for result in results.get("results", []):
                        doc = result.get("document", {}).get("structData", {})
                        if doc:
                            doc["_source"] = ds_name  # Tag with source
                            data.append(doc)
                    logger.info(f"Retrieved {len(data)} records from {ds_name}")
                    return data
                else:
                    logger.warning(f"Search failed for {ds_name}: {response.status_code}")
                    return []
            except Exception as e:
                logger.error(f"Error searching {ds_name}: {str(e)}")
                return []
        
        # Query relevant data stores in parallel
        retrieved_data = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(search_datastore, name, ds_id): name 
                      for name, ds_id in relevant_stores.items()}
            
            for future in as_completed(futures):
                data = future.result()
                retrieved_data.extend(data)
        
        logger.info(f"Retrieved {len(retrieved_data)} total records from {len(relevant_stores)} data stores")

        # Fallback: If search returns nothing, try broad search across all stores
        if not retrieved_data:
            logger.info("No search results, trying broad search")
            
            def broad_search_datastore(ds_name, ds_id):
                """Broad search a single data store"""
                search_url = f"https://discoveryengine.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/collections/default_collection/dataStores/{ds_id}/servingConfigs/default_search:search"
                broad_queries = ["data", "record", "information"]
                data = []
                seen_ids = set()
                
                for broad_query in broad_queries:
                    try:
                        response = requests.post(
                            search_url,
                            headers=headers,
                            json={"query": broad_query, "pageSize": 20},
                            timeout=10
                        )
                        if response.status_code == 200:
                            results = response.json()
                            for result in results.get("results", []):
                                doc = result.get("document", {}).get("structData", {})
                                doc_id = result.get("document", {}).get("id", "")
                                if doc and doc_id not in seen_ids:
                                    doc["_source"] = ds_name
                                    data.append(doc)
                                    seen_ids.add(doc_id)
                            if len(data) >= 10:
                                break
                    except Exception as e:
                        logger.error(f"Broad search error for {ds_name}: {str(e)}")
                        continue
                return data
            
            # Broad search relevant data stores in parallel
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(broad_search_datastore, name, ds_id): name 
                          for name, ds_id in relevant_stores.items()}
                
                for future in as_completed(futures):
                    data = future.result()
                    retrieved_data.extend(data)
            
            logger.info(f"Retrieved {len(retrieved_data)} records from broad search")
            
            # If still no data, return error
            if not retrieved_data:
                return Response(json.dumps({
                    "response": "I couldn't find any data in the database.",
                    "sessionId": "",
                    "dataCount": 0
                }), mimetype="application/json", headers={"Access-Control-Allow-Origin": "*"})

        # Step 2: Use Gemini to generate natural language response with conversation history
        session_history = SESSIONS[session_id]["history"]
        
        # Build conversation context
        history_context = ""
        if session_history:
            history_context = "\n\nConversation History:\n"
            for i, turn in enumerate(session_history[-3:], 1):  # Last 3 turns
                history_context += f"Q{i}: {turn['query']}\nA{i}: {turn['response'][:200]}...\n\n"
        
        prompt = f"""You are an intelligent data assistant. A user has asked a question and I've retrieved relevant records from multiple data sources.{history_context}
Current Question: "{user_query}"

Retrieved Data (JSON format):
{json.dumps(retrieved_data, indent=2)}

Note: Each record has a "_source" field indicating which data store it came from (client-portfolio, loginevents, users, productclicks, or products).

Your task:
1. Consider the conversation history when answering
2. If the user refers to previous queries ("that", "those", "it"), use context
3. Answer the question accurately based ONLY on the provided data
4. If the question asks for sorting, filtering, comparison, or analysis - perform it
5. Format your response in a clear, conversational way
6. Use proper formatting for numbers (e.g., $150,000)
7. If data comes from multiple sources, mention which source when relevant
8. If the data doesn't fully answer the question, say so clearly

Provide your answer now:"""

        gemini_response = requests.post(
            GEMINI_URL,
            headers=headers,
            json={
                "contents": [{
                    "role": "user",
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2048,
                    "topP": 0.8,
                    "topK": 40
                }
            }
        )

        if gemini_response.status_code != 200:
            logger.error(f"Gemini API error: {gemini_response.text}")
            # Fallback: return raw data
            answer = f"Found {len(retrieved_data)} records:\n\n{json.dumps(retrieved_data, indent=2)}"
        else:
            gemini_result = gemini_response.json()
            answer = gemini_result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Unable to generate response")

        # Store in session history
        SESSIONS[session_id]["history"].append({
            "query": user_query,
            "response": answer.strip(),
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep only last 10 turns
        if len(SESSIONS[session_id]["history"]) > 10:
            SESSIONS[session_id]["history"] = SESSIONS[session_id]["history"][-10:]
        
        # Return successful response
        return Response(json.dumps({
            "response": answer.strip(),
            "sessionId": session_id,
            "dataCount": len(retrieved_data)
        }), mimetype="application/json", headers={"Access-Control-Allow-Origin": "*"})

    except Exception as e:
        logger.exception("Unexpected error processing request")
        return Response(json.dumps({
            "response": f"Error: {str(e)}",
            "sessionId": "",
            "dataCount": 0
        }), status=500, mimetype="application/json", headers={"Access-Control-Allow-Origin": "*"})
    