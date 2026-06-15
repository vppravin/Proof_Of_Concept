import json
import logging
import ssl
import time
import re
from vertexai import agent_engines
from urllib3.exceptions import SSLError

# Configure logging with Cloud Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add stdout handler so logs go to Cloud Run logs
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - [ROUTING_TOOLS] - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Response size limit (30KB)
MAX_RESPONSE_SIZE = 30 * 1024

def sanitize_response(response: str) -> str:
    """
    Sanitize response to ensure it's safe for UI display.
    
    Args:
        response: Raw response string
    
    Returns:
        Sanitized response string
    """
    print(f"[ROUTING_TOOLS] [SANITIZE] Starting sanitization, input size: {len(response)} chars")
    logger.info(f"[SANITIZE] Starting sanitization, input size: {len(response)} chars")
    
    # Step 1: Remove null bytes and control characters
    print(f"[ROUTING_TOOLS] [SANITIZE] Step 1: Removing null/control characters")
    logger.info(f"[SANITIZE] Step 1: Removing null/control characters")
    sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', response)
    print(f"[ROUTING_TOOLS] [SANITIZE] Step 1 complete, size: {len(sanitized)} chars")
    logger.info(f"[SANITIZE] Step 1 complete, size: {len(sanitized)} chars")
    
    # Step 2: Ensure valid UTF-8
    print(f"[ROUTING_TOOLS] [SANITIZE] Step 2: Ensuring valid UTF-8")
    logger.info(f"[SANITIZE] Step 2: Ensuring valid UTF-8")
    try:
        sanitized = sanitized.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
        print(f"[ROUTING_TOOLS] [SANITIZE] Step 2 complete, size: {len(sanitized)} chars")
        logger.info(f"[SANITIZE] Step 2 complete, size: {len(sanitized)} chars")
    except Exception as e:
        print(f"[ROUTING_TOOLS] [SANITIZE] UTF-8 encoding error: {e}")
        logger.error(f"[SANITIZE] UTF-8 encoding error: {e}")
    
    # Step 3: Truncate if too large
    if len(sanitized) > MAX_RESPONSE_SIZE:
        print(f"[ROUTING_TOOLS] [SANITIZE] Step 3: Response too large ({len(sanitized)} chars), truncating to {MAX_RESPONSE_SIZE}")
        logger.warning(f"[SANITIZE] Step 3: Response too large ({len(sanitized)} chars), truncating to {MAX_RESPONSE_SIZE}")
        sanitized = sanitized[:MAX_RESPONSE_SIZE] + "\n\n[Response truncated due to size limit. Please refine your query for more specific results.]"
        print(f"[ROUTING_TOOLS] [SANITIZE] Step 3 complete, final size: {len(sanitized)} chars")
        logger.info(f"[SANITIZE] Step 3 complete, final size: {len(sanitized)} chars")
    else:
        print(f"[ROUTING_TOOLS] [SANITIZE] Step 3: Size OK, no truncation needed")
        logger.info(f"[SANITIZE] Step 3: Size OK, no truncation needed")
    
    print(f"[ROUTING_TOOLS] [SANITIZE] ✅ Sanitization complete, final size: {len(sanitized)} chars")
    logger.info(f"[SANITIZE] ✅ Sanitization complete, final size: {len(sanitized)} chars")
    return sanitized

def call_sub_agent(agent_id: str, prompt: str, max_retries: int = 3) -> dict:
    """
    Call sub-agent with retry logic and detailed logging.
    
    Args:
        agent_id: The Agent Engine ID to call
        prompt: The user prompt to send
        max_retries: Number of retry attempts (default: 3)
    
    Returns:
        Dictionary with 'result' or 'error' key
    """
    
    for attempt in range(max_retries):
        try:
            print(f"[ROUTING_TOOLS] [ATTEMPT {attempt + 1}/{max_retries}] Calling agent: {agent_id}")
            print(f"[ROUTING_TOOLS] [ATTEMPT {attempt + 1}/{max_retries}] Prompt: {prompt[:100]}...")
            logger.info(f"[ATTEMPT {attempt + 1}/{max_retries}] Calling agent: {agent_id}")
            logger.info(f"[ATTEMPT {attempt + 1}/{max_retries}] Prompt: {prompt[:100]}...")
            
            # Get agent engine
            print(f"[ROUTING_TOOLS] [STEP 1] Getting agent engine...")
            logger.info(f"[STEP 1] Getting agent engine...")
            remote_agent = agent_engines.get(agent_id)
            print(f"[ROUTING_TOOLS] [STEP 1] ✅ Agent engine retrieved")
            logger.info(f"[STEP 1] ✅ Agent engine retrieved")
            
            # Stream query
            print(f"[ROUTING_TOOLS] [STEP 2] Starting stream_query...")
            logger.info(f"[STEP 2] Starting stream_query...")
            full_response = []
            event_count = 0
            start_time = time.time()
            
            for event in remote_agent.stream_query(message=prompt, user_id="test-user"):
                event_count += 1
                elapsed = time.time() - start_time
                print(f"[ROUTING_TOOLS] [STEP 2] Event #{event_count} received (elapsed: {elapsed:.1f}s)")
                logger.info(f"[STEP 2] Event #{event_count} received (elapsed: {elapsed:.1f}s)")
                
                content = event.get("content", {})
                parts = content.get("parts", [])
                
                for part in parts:
                    if "text" in part:
                        text_chunk = part["text"]
                        full_response.append(text_chunk)
                        print(f"[ROUTING_TOOLS] [STEP 2] Collected {len(text_chunk)} chars")
                        logger.info(f"[STEP 2] Collected {len(text_chunk)} chars")
            
            # Success
            total_time = time.time() - start_time
            result = "".join(full_response)
            print(f"[ROUTING_TOOLS] [STEP 3] ✅ Stream completed in {total_time:.1f}s")
            print(f"[ROUTING_TOOLS] [STEP 3] Total events: {event_count}, Response length: {len(result)} chars")
            logger.info(f"[STEP 3] ✅ Stream completed in {total_time:.1f}s")
            logger.info(f"[STEP 3] Total events: {event_count}, Response length: {len(result)} chars")
            
            # Sanitize response
            print(f"[ROUTING_TOOLS] [STEP 4] Starting response sanitization...")
            logger.info(f"[STEP 4] Starting response sanitization...")
            sanitized_result = sanitize_response(result) if result else "No response received"
            print(f"[ROUTING_TOOLS] [STEP 4] ✅ Sanitization complete")
            logger.info(f"[STEP 4] ✅ Sanitization complete")
            
            # Log first 200 chars of sanitized response
            preview = sanitized_result[:200].replace('\n', ' ')
            print(f"[ROUTING_TOOLS] [STEP 5] Response preview: {preview}...")
            print(f"[ROUTING_TOOLS] [STEP 5] Final response size: {len(sanitized_result)} chars")
            logger.info(f"[STEP 5] Response preview: {preview}...")
            logger.info(f"[STEP 5] Final response size: {len(sanitized_result)} chars")
            print(f"[ROUTING_TOOLS] [SUCCESS] Returning sanitized response from agent: {agent_id}")
            logger.info(f"[SUCCESS] Returning sanitized response from agent: {agent_id}")
            
            return {"result": sanitized_result}
            
        except (SSLError, ssl.SSLEOFError) as e:
            # SSL/Connection errors - retry with backoff
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(f"[RETRY] SSL error on attempt {attempt + 1}, retrying in {wait_time}s: {str(e)}")
                time.sleep(wait_time)
            else:
                logger.error(f"[FAILED] SSL error after {max_retries} attempts: {str(e)}")
                return {"error": f"Connection failed after {max_retries} attempts. Please try again later."}
                
        except Exception as e:
            # Other errors - log and return
            logger.error(f"[ERROR] Error calling agent {agent_id}: {str(e)}")
            logger.error(f"[ERROR] Exception type: {type(e).__name__}")
            
            # If not last attempt, retry
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"[RETRY] Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                return {"error": str(e)}
    
    # Should never reach here, but just in case
    return {"error": "Maximum retries exceeded"}


# Tool 1: Get the list of prioritized leads from SFDC
def get_prioritized_leads(prompt: str) -> dict:
    """
    Sends a user prompt to the lead prioritizer agent and returns its response.

    Args:
        prompt (str): The user's input prompt asking for prioritized leads.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/6508120375480549376"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)
    
#Tool 2:Create task for the lead in sfdc
def task_creation(prompt:str) -> dict:
    """
    Sends a user prompt to the sfdc_task creator agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks to create task of the lead present in sfdc to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/5513810020250157056"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 3: Gives the details of fund invested by the customer
def returns_on_fund(prompt: str) -> dict:
    """
    Sends a user prompt to the Fund_Performance_Analyzer and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the details on the funds invested by the customer to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/8726002454472163328"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 4: Map assistant
def map_assistant(prompt: str) -> dict:
    """
    Sends a user prompt to the Maps agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the location,address, nearby restaurants and so on to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/8597227652627038208"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 5: provides the details on sma activity of the lead
def sma_activity(prompt: str) -> dict:
    """
    Sends a user prompt to the SMA agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the details on SMA activity of the lead to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/1659854639127855104"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 6: provides the information on stocks
def stocks_info(prompt: str) -> dict:
    """
    Sends a user prompt to the stocks info agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the details on stock prices, trends, and chart visualizations to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/3536729783834509312"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 7: provides details on sdi activity of the lead
def sdi_activity(prompt: str) -> dict:
    """
    Sends a user prompt to the SDI agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the details on SDI activity of the lead to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/6018213178515652608"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 8: provides details on checking activity of the lead
def checking_activity(prompt: str) -> dict:
    """
    Sends a user prompt to the Checking agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the analyzing a customer's Checking account transaction and to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/5951785084011937792"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 9: Provides 360 view about the lead
def _360_view(prompt: str) -> dict:
    """
    Sends a user prompt to the agent 360 and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the 360 degree view to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/4243372712866611200"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 10: provides the comparison on sdi accounts of the lead
def lead_comparison(prompt: str) -> dict:
    """
    Sends a user prompt to the sdi_comparison agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the comparison on sdi account activities of the leads to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/879183791220850688"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)

#Tool 11: provides details on stocks sold by the lead
def stock_sales(prompt: str) -> dict:
    """
    Sends a user prompt to the stocks_sales_trend agent and returns its response.

    Args:
        prompt (str): The user's input prompt that asks for the Analyzes on sold stocks for a given lead to be processed by the agent.

    Returns:
        dict: Response with 'result' or 'error' key
    """
    AGENT_ENGINE_ID = "projects/146646146609/locations/us-central1/reasoningEngines/7659915980180553728"
    return call_sub_agent(AGENT_ENGINE_ID, prompt)
