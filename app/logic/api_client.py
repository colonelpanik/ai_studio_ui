# app/logic/api_client.py
# Handles interactions with the Google Generative AI API.
import google.generativeai as genai
import google.ai.generativelanguage as glm
# Import types that ARE in types module
from google.generativeai.types import GenerationConfig, Model
# Import constants/enums that were likely at the top level in v0.4.1
import google.generativeai as genai
import logging
from functools import lru_cache # Cache model listing

logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_MODEL = "models/gemini-1.5-flash-latest"
FALLBACK_MODEL_MAX_OUTPUT_TOKENS = 65536 # Default if API fails
DEFAULT_SAFETY_SETTINGS = [
    # Using library defaults is usually sufficient unless specific tuning is needed.
    # Example:
    # { HarmCategory.HARM_CATEGORY_HARASSMENT: SafetySetting.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE },
    # ... add others if needed
]

# --- API Configuration ---
def configure_api(api_key: str) -> bool:
    """Configures the GenAI API key."""
    # IN: api_key: str; OUT: bool # Configures genai API key, returns success.
    if not api_key:
        logger.error("API configuration failed: API key is empty.")
        return False
    try:
        genai.configure(api_key=api_key)
        logger.info(f"GenAI API configured successfully (Key ending: ...{api_key[-4:]}).")
        # Clear cache when API key changes
        list_available_models.cache_clear()
        get_model_info.cache_clear()
        return True
    except Exception as e:
        logger.error(f"GenAI API configuration failed: {e}", exc_info=True)
        return False

# --- Model Listing & Info ---
@lru_cache(maxsize=1) # Cache the list of models per API key session
def list_available_models() -> list[str]:
    """Lists available generative models."""
    # IN: None; OUT: List[str] # Lists usable generative models from API, cached.
    model_list = []
    try:
        logger.info("Fetching available models from API...")
        for m in genai.list_models():
            # Filter for models supporting 'generateContent'
            if 'generateContent' in m.supported_generation_methods:
                model_list.append(m.name)
        model_list.sort()
        logger.info(f"Found {len(model_list)} usable models.")
    except Exception as e:
        logger.error(f"Error listing models: {e}", exc_info=True)
        # Return empty list on error, cache will store this empty list
    return model_list

@lru_cache(maxsize=16) # Cache info for a few models
def get_model_info(model_name: str) -> Model | None:
    """Gets detailed information for a specific model."""
    # IN: model_name: str; OUT: Optional[Model] # Fetches Model object from API, cached.
    if not model_name: return None
    try:
        logger.info(f"Fetching model info for: {model_name}")
        model_info = genai.get_model(model_name)
        logger.debug(f"Successfully fetched info for {model_name}")
        return model_info
    except Exception as e:
        logger.error(f"Error getting model info for {model_name}: {e}", exc_info=True)
        return None

def get_model_output_limit(model_name: str) -> int:
    """Gets the output token limit for a model, with fallback."""
    # IN: model_name: str; OUT: int # Gets model output token limit, uses fallback on error.
    model_info = get_model_info(model_name)
    if model_info and hasattr(model_info, 'output_token_limit') and model_info.output_token_limit:
        limit = int(model_info.output_token_limit) # Ensure it's an int
        logger.info(f"Output token limit for {model_name}: {limit}")
        return limit
    else:
        logger.warning(f"Could not retrieve output token limit for {model_name}. Using fallback: {FALLBACK_MODEL_MAX_OUTPUT_TOKENS}")
        return FALLBACK_MODEL_MAX_OUTPUT_TOKENS

# --- Text Generation ---
def generate_text(model_name: str, prompt: str, generation_config_dict: dict, history: list = None) -> tuple[str | None, str | None]:
    """Generates text using the specified model and config."""
    # IN: model_name, prompt, gen_config_dict, history; OUT: (text, error_msg) # Generates text via API.
    logger.info(f"Generating text with model {model_name} (prompt length: {len(prompt)})")
    try:
        model = genai.GenerativeModel(model_name)
        gen_config_obj = GenerationConfig(**generation_config_dict)
        logger.debug(f"Generation Config: {generation_config_dict}")

        # Use start_chat if history is provided
        if history:
            logger.debug(f"Starting chat with history length: {len(history)}")
            chat = model.start_chat(history=history)
            response = chat.send_message(
                prompt, # Send only the new prompt to chat object
                stream=False, # Simplification: Use non-streaming for now
                generation_config=gen_config_obj,
                safety_settings=DEFAULT_SAFETY_SETTINGS
            )
        else:
            logger.debug("Generating content without history.")
            response = model.generate_content(
                prompt, # Send the full prompt (potentially including context/instruction)
                stream=False,
                generation_config=gen_config_obj,
                safety_settings=DEFAULT_SAFETY_SETTINGS
            )

        # Check for blocked response or missing candidates
        if not response.candidates:
            block_reason = "Unknown"
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                block_reason = response.prompt_feedback.block_reason.name
            logger.error(f"Generation failed: Response blocked or empty. Reason: {block_reason}. Feedback: {getattr(response, 'prompt_feedback', 'N/A')}")
            return None, f"Response blocked by content filter ({block_reason})."

        # Extract text (handle potential variations in response structure)
        response_text = getattr(response, 'text', None)
        if response_text is None:
             # Fallback check within candidates if text isn't top-level
             if response.candidates and hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts'):
                  response_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, 'text'))

        if response_text is None:
             logger.error(f"Generation failed: Could not extract text from response. Response structure: {response}")
             return None, "Failed to extract text from model response."

        logger.info(f"Text generation successful (response length: {len(response_text)}).")
        return response_text, None

    except Exception as e:
        logger.error(f"Error during text generation API call: {e}", exc_info=True)
        # Provide more specific error feedback if possible
        if "API key not valid" in str(e):
            return None, "API key not valid. Please check your key."
        elif "permission" in str(e).lower():
            return None, f"Permission denied for model {model_name}. Check API key permissions."
        # Add more specific error checks if needed
        return None, f"API error: {e}"

# --- Token Counting ---
def count_tokens(model_name: str, text_to_count: str) -> tuple[int | None, str | None]:
    """Counts tokens in the provided text using the specified model."""
    # IN: model_name, text_to_count; OUT: (count, error_msg) # Counts tokens via API.
    if not text_to_count.strip():
        return 0, None # No tokens for empty string

    logger.info(f"Counting tokens with model {model_name} (text length: {len(text_to_count)})")
    try:
        model = genai.GenerativeModel(model_name) # Instance needed for count_tokens
        count_response = model.count_tokens(text_to_count)
        token_count = count_response.total_tokens
        logger.info(f"Token count successful: {token_count}")
        return token_count, None
    except Exception as e:
        logger.error(f"Error counting tokens: {e}", exc_info=True)
        return None, f"Token counting error: {e}"