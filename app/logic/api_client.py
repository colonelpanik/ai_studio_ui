# app/logic/api_client.py
# Handles interactions with the Google Generative AI API.
import google.generativeai as genai
# --- MODIFIED IMPORTS ---
import google.generativeai.types as genai_types # Use alias for clarity
from google.generativeai.types import GenerationConfig, Model # Keep specific types
import google.ai.generativelanguage as glm # Keep for potential other uses if needed
# --- End MODIFIED IMPORTS ---
import logging
from functools import lru_cache # Cache model listing

logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_MODEL = "models/gemini-1.5-flash-latest" # Keep default
FALLBACK_MODEL_MAX_OUTPUT_TOKENS = 65536
DEFAULT_SAFETY_SETTINGS = [ ] # Keep default

# --- REMOVED static GROUNDING_TOOL definition ---

# --- API Configuration ---
def configure_api(api_key: str) -> bool:
    """Configures the GenAI API key."""
    if not api_key:
        logger.error("API configuration failed: API key is empty.")
        return False
    try:
        # Using genai.configure might be simpler than managing a client instance explicitly
        # unless advanced client features are needed. Stick with configure for now.
        genai.configure(api_key=api_key)
        logger.info(f"GenAI API configured successfully (Key ending: ...{api_key[-4:]}).")
        list_available_models.cache_clear()
        get_model_info.cache_clear()
        return True
    except Exception as e:
        logger.error(f"GenAI API configuration failed: {e}", exc_info=True)
        return False

# --- Model Listing & Info ---
@lru_cache(maxsize=1)
def list_available_models() -> list[str]:
    """Lists available generative models, preferring those supporting tools."""
    model_list = []
    try:
        logger.info("Fetching available models from API...")
        for m in genai.list_models():
            # Check for generateContent support explicitly
            if 'generateContent' in m.supported_generation_methods:
                # Prioritize models likely supporting tools (heuristic)
                model_list.append(m.name)
                # Include others just in case, but maybe list them later?
                # elif not m.name.startswith('models/embedding'): # Avoid embedding models
                #    model_list.append(m.name) # Keep other content models
            # Simple check based on user example - might need refinement
            # if hasattr(m, 'tool_config') or m.name.startswith('models/gemini-1.5'):
            #      model_list.append(m.name)

        model_list = sorted(list(set(model_list))) # Unique and sorted
        logger.info(f"Found {len(model_list)} usable models (supporting generateContent, preferring tool support).")
        if not model_list:
            logger.warning("No models found supporting generateContent. Check API key/permissions.")
    except Exception as e:
        logger.error(f"Error listing models: {e}", exc_info=True)
    return model_list

@lru_cache(maxsize=16)
def get_model_info(model_name: str) -> Model | None:
    """Gets detailed information for a specific model."""
    if not model_name: return None
    try:
        logger.info(f"Fetching model info for: {model_name}")
        full_model_name = f"models/{model_name}" if not model_name.startswith("models/") else model_name
        model_info = genai.get_model(full_model_name)
        logger.debug(f"Successfully fetched info for {model_name}")
        return model_info
    except Exception as e:
        logger.error(f"Error getting model info for {model_name}: {e}", exc_info=True)
        return None

def get_model_output_limit(model_name: str) -> int:
    """Gets the output token limit for a model, with fallback."""
    model_info = get_model_info(model_name)
    limit = FALLBACK_MODEL_MAX_OUTPUT_TOKENS # Start with fallback
    if model_info and hasattr(model_info, 'output_token_limit') and model_info.output_token_limit:
        try:
            limit = int(model_info.output_token_limit)
            logger.info(f"Output token limit for {model_name}: {limit}")
        except ValueError:
            logger.warning(f"Could not parse output token limit for {model_name}. Using fallback.")
    else:
        logger.warning(f"Could not retrieve output token limit for {model_name}. Using fallback.")
    return limit

# --- Text Generation ---
def generate_text(
    model_name: str,
    prompt: str,
    generation_config_dict: dict,
    enable_grounding: bool = False,
    grounding_threshold: float = 0.0, # <-- ADDED: Threshold parameter
    history: list = None
) -> tuple[str | None, str | None]:
    """Generates text using the specified model and config, optionally with grounding and threshold."""
    logger.info(f"Generating text with model {model_name} (prompt length: {len(prompt)}, Grounding: {enable_grounding}, Threshold: {grounding_threshold})")
    try:
        model = genai.GenerativeModel(model_name)
        gen_config_obj = GenerationConfig(**generation_config_dict)
        logger.debug(f"Generation Config: {generation_config_dict}")

        # --- REFACTORED: Dynamically create grounding tool ---
        tools_list = None
        if enable_grounding:
            logger.info("Grounding enabled. Constructing tool...")
            try:
                dynamic_retrieval_config = None
                if grounding_threshold > 0.0: # Only set threshold if > 0
                    dynamic_retrieval_config = genai_types.DynamicRetrievalConfig(
                        dynamic_threshold=grounding_threshold
                    )
                    logger.info(f"Using dynamic grounding threshold: {grounding_threshold}")

                GoogleSearch_retrieval_obj = genai_types.GoogleSearchRetrieval(
                    disable_attribution=False, # Keep attribution enabled
                    dynamic_retrieval_config=dynamic_retrieval_config # Will be None if threshold is 0.0
                )
                grounding_tool_dynamic = genai_types.Tool(
                    GoogleSearch_retrieval=GoogleSearch_retrieval_obj
                )
                tools_list = [grounding_tool_dynamic]
                logger.info("Grounding tool constructed successfully.")
            except AttributeError as tool_attr_err:
                logger.error(f"Failed to construct grounding tool: Likely missing types in 'google.generativeai.types'. Error: {tool_attr_err}", exc_info=True)
                return None, f"Error creating grounding tool: {tool_attr_err}. Check library version."
            except Exception as tool_err:
                logger.error(f"Failed to construct grounding tool: {tool_err}", exc_info=True)
                return None, f"Error creating grounding tool: {tool_err}"
        # --- End REFACTORED ---

        # Determine API call arguments (shared between chat and generate_content)
        api_kwargs = {
            "generation_config": gen_config_obj,
            "safety_settings": DEFAULT_SAFETY_SETTINGS,
            "tools": tools_list # Pass the dynamically created tools list
        }

        # Use start_chat if history is provided
        if history:
            logger.debug(f"Starting chat with history length: {len(history)}")
            chat = model.start_chat(history=history)
            response = chat.send_message(
                prompt,
                stream=False,
                **api_kwargs
            )
        else:
            logger.debug("Generating content without history.")
            response = model.generate_content(
                prompt,
                stream=False,
                **api_kwargs
            )

        # --- REFACTORED: Citation / Grounding Metadata Extraction ---
        citations_extracted = [] # List to hold tuples (uri, title)
        rendered_web_content = None # To store the web snippet if available
        if enable_grounding:
            try:
                # Check candidates first for citation_metadata (older style?)
                if response.candidates and hasattr(response.candidates[0], 'citation_metadata'):
                    metadata = response.candidates[0].citation_metadata
                    if metadata and hasattr(metadata, 'citation_sources'):
                        for source in metadata.citation_sources:
                            citations_extracted.append( (getattr(source, 'uri', None), getattr(source, 'title', None)) )
                        logger.info(f"Extracted {len(citations_extracted)} citations via citation_metadata.")

                # Check response level for grounding_metadata (newer style from user example?)
                elif hasattr(response, 'grounding_metadata'):
                    grounding_meta = response.grounding_metadata
                    if grounding_meta:
                        # Extract web search results if available
                        if hasattr(grounding_meta, 'web_search_results'):
                                for result in grounding_meta.web_search_results:
                                    citations_extracted.append( (getattr(result, 'uri', None), getattr(result, 'title', None)) )
                                logger.info(f"Extracted {len(citations_extracted)} citations via grounding_metadata.web_search_results.")
                        # Extract rendered content snippet if available
                        if hasattr(grounding_meta, 'search_entry_point') and grounding_meta.search_entry_point:
                                rendered_web_content = getattr(grounding_meta.search_entry_point, 'rendered_content', None)
                                if rendered_web_content:
                                    logger.info("Extracted rendered web content snippet from grounding metadata.")

                # Fallback check inside candidates for grounding_metadata
                elif response.candidates and hasattr(response.candidates[0], 'grounding_metadata'):
                    grounding_meta = response.candidates[0].grounding_metadata
                    # Repeat extraction logic as above if needed here
                    if grounding_meta:
                        if hasattr(grounding_meta, 'web_search_results'):
                            for result in grounding_meta.web_search_results:
                                    citations_extracted.append( (getattr(result, 'uri', None), getattr(result, 'title', None)) )
                            logger.info(f"Extracted {len(citations_extracted)} citations via candidates[0].grounding_metadata.web_search_results.")
                        if hasattr(grounding_meta, 'search_entry_point') and grounding_meta.search_entry_point:
                            rendered_web_content = getattr(grounding_meta.search_entry_point, 'rendered_content', None)
                            if rendered_web_content:
                                    logger.info("Extracted rendered web content snippet from candidates[0].grounding_metadata.")

                else:
                    logger.info("Grounding enabled, but no citation or grounding metadata found in response.")

            except Exception as cite_err:
                logger.warning(f"Could not extract grounding/citation metadata: {cite_err}", exc_info=True)
        # --- End REFACTORED ---

        # Check for blocked response or missing candidates
        if not response.candidates:
            block_reason = "Unknown"
            try:
                if response.prompt_feedback.block_reason: block_reason = response.prompt_feedback.block_reason.name
            except AttributeError: pass
            logger.error(f"Generation failed: Response blocked or empty. Reason: {block_reason}. Feedback: {getattr(response, 'prompt_feedback', 'N/A')}")
            return None, f"Response blocked by content filter ({block_reason})."

        # Extract text
        response_text = None
        try: response_text = response.text
        except ValueError: logger.warning(".text attribute error, checking parts.")
        except AttributeError: logger.warning(".text attribute missing, checking parts.")
        if response_text is None:
            if response.candidates and hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts'):
                response_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, 'text'))
        if response_text is None:
            logger.error(f"Generation failed: Could not extract text from response. Response structure: {response}")
            return None, "Failed to extract text from model response."

        # Append extracted citations/web content
        if citations_extracted:
            citation_str = "\n\n**Sources:**\n"
            unique_sources = list(dict.fromkeys(citations_extracted)) # Remove duplicates based on (uri, title) pair
            for i, (uri, title) in enumerate(unique_sources):
                display_uri = uri or 'Source link unavailable'
                display_text = title or display_uri
                if uri: citation_str += f"{i+1}. [{display_text}]({uri})\n"
                else: citation_str += f"{i+1}. {display_text}\n"
            response_text += citation_str
            logger.debug("Appended grounding citations to response text.")
        if rendered_web_content:
            # Optionally add the web snippet
            # response_text += f"\n\n**Web Content Snippet:**\n```html\n{rendered_web_content}\n```"
            logger.debug("Web content snippet was extracted but not appended by default.")


        logger.info(f"Text generation successful (response length: {len(response_text)}).")
        return response_text, None

    except Exception as e:
        # Handle errors (keep existing specific checks, add more if needed)
        logger.error(f"Error during text generation API call: {e}", exc_info=True)
        error_str = str(e)
        # ... (keep existing specific error handling) ...
        if "API key not valid" in error_str:
            return None, "API key not valid. Please check your key."
        elif "permission" in error_str.lower():
            denied_model = model_name
            try:
                if "PermissionDenied: 403" in error_str and "permission for" in error_str:
                    denied_model = error_str.split("permission for '")[1].split("'")[0]
            except IndexError: pass
            return None, f"Permission denied for resource '{denied_model}'. Check API key permissions."
        elif "User location is not supported" in error_str:
            return None, f"API Error: User location is not supported for the model or feature (e.g., grounding). ({e})"
        elif "grounding" in error_str.lower() or "tool" in error_str.lower():
            # Make error more specific if possible
            if "retrieval configuration" in error_str.lower():
                return None, f"API Error: Invalid grounding retrieval configuration (e.g., threshold). ({e})"
            return None, f"API Error related to Grounding/Tools: Model may not support it or config is wrong. ({e})"
        elif "Deadline Exceeded" in error_str:
            return None, f"API Error: Request timed out (Deadline Exceeded). Try reducing complexity or context. ({e})"
        return None, f"API error: {e}"


# --- Token Counting ---
def count_tokens(model_name: str, text_to_count: str) -> tuple[int | None, str | None]:
    """Counts tokens in the provided text using the specified model."""
    if not text_to_count.strip(): return 0, None
    logger.info(f"Counting tokens with model {model_name} (text length: {len(text_to_count)})")
    try:
        model = genai.GenerativeModel(model_name)
        count_response = model.count_tokens(text_to_count)
        token_count = count_response.total_tokens
        logger.info(f"Token count successful: {token_count}")
        return token_count, None
    except Exception as e:
        logger.error(f"Error counting tokens: {e}", exc_info=True)
        return None, f"Token counting error: {e}"