# dictionar.py
import requests
import json
import logging

# Use logging instead of print for better integration
log = logging.getLogger(__name__)

def get_definitions(word, max_definitions=7):
    """
    Fetches definitions, phonetics, and audio for a given English word
    from the dictionaryapi.dev API.

    Args:
        word (str): The English word to look up.
        max_definitions (int): The maximum number of definitions to return.

    Returns:
        str: A JSON string containing the results (phonetic, audio, definitions)
             or an error message.
    """
    if not isinstance(word, str) or not word.strip():
        log.warning("get_definitions called with invalid word input.")
        return json.dumps({"error": "Noto'g'ri so'z kiritildi."}, ensure_ascii=False, indent=4)

    word = word.strip().lower() # Normalize word
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    log.info(f"Requesting definition for '{word}' from {url}")

    try:
        # Increased timeout slightly for potentially slower connections
        response = requests.get(url, timeout=15)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        try:
            res = response.json()
        except json.JSONDecodeError:
            log.error(f"API JSON decode error for '{word}'. Status: {response.status_code}. Response text: {response.text[:200]}...")
            return json.dumps({"error": "API dan noto‘g‘ri JSON javob keldi."}, ensure_ascii=False, indent=4)

        # --- Process successful response (expected: list of entries) ---
        if isinstance(res, list) and res:
            word_data = res[0]  # API often returns a list, take the first entry
            phonetics = word_data.get("phonetics", [])
            audio_url = None
            phonetic_text = None

            # Find best phonetic text and audio URL
            # Prioritize audio with .mp3 extension and text availability
            best_phonetic = {}
            for phonetic in phonetics:
                has_text = bool(phonetic.get("text"))
                has_audio = bool(phonetic.get("audio"))
                is_mp3 = has_audio and phonetic['audio'].endswith('.mp3')

                # Simple priority: text + mp3 > text + any audio > text only > mp3 only > any audio > fallback
                current_score = (has_text * 4) + (is_mp3 * 2) + (has_audio * 1)

                if not best_phonetic or current_score > best_phonetic['score']:
                     best_phonetic = {
                         'score': current_score,
                         'text': phonetic.get("text"),
                         'audio': phonetic.get("audio") if has_audio else None
                     }
                # Early exit if we found text + mp3
                if has_text and is_mp3:
                    break

            phonetic_text = best_phonetic.get('text')
            audio_url = best_phonetic.get('audio')

            # Collect definitions up to the limit
            definitions = []
            meanings = word_data.get("meanings", [])
            definitions_count = 0
            stop_outer = False
            for meaning in meanings:
                if stop_outer: break
                part_of_speech = meaning.get("partOfSpeech", "") # Get part of speech
                # Optionally add part of speech to output: definitions.append(f"*({part_of_speech})*")

                for definition_item in meaning.get("definitions", []):
                    if definitions_count < max_definitions:
                        definition_text = definition_item.get('definition')
                        if definition_text: # Ensure definition text exists
                            definitions.append(f"👉 {definition_text}")
                            definitions_count += 1
                    else:
                        stop_outer = True # Signal to break outer loop
                        break # Break inner loop

            result = {
                "phonetic": phonetic_text if phonetic_text else "Mavjud emas",
                "audio": audio_url,  # Remains None if no suitable audio found
                "definitions": definitions if definitions else ["Ta'riflar topilmadi."]
            }
            log.info(f"Successfully found definition data for '{word}'.")
            return json.dumps(result, ensure_ascii=False, indent=4)

        # --- Handle API error response (expected: dict with 'title') ---
        elif isinstance(res, dict) and res.get("title"):
            error_message = res.get("message", "Aniqlanmagan xato.")
            log.warning(f"API returned error for '{word}': Title: {res.get('title')}, Message: {error_message}")
            # Use title if informative, otherwise provide generic message
            if res.get("title") == "No Definitions Found":
                 return json.dumps({"error": f"'{word}' uchun ta'rif topilmadi."}, ensure_ascii=False, indent=4)
            else:
                 return json.dumps({"error": f"API xatosi: {res.get('title')}"}, ensure_ascii=False, indent=4)

        # --- Handle unexpected response format ---
        else:
            log.warning(f"Unexpected API response format for '{word}'. Type: {type(res)}, Response: {str(res)[:200]}...")
            return json.dumps({"error": "API dan kutilmagan javob formati."}, ensure_ascii=False, indent=4)

    # --- Handle Network/Request Errors ---
    except requests.exceptions.Timeout:
        log.error(f"API request timed out for '{word}'")
        return json.dumps({"error": "API javob qaytarish vaqti tugadi."}, ensure_ascii=False, indent=4)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            log.warning(f"Word '{word}' not found (404).")
            return json.dumps({"error": f"'{word}' so‘zi topilmadi (404)."}, ensure_ascii=False, indent=4)
        else:
            log.error(f"HTTP error for '{word}': {e}")
            return json.dumps({"error": f"Server bilan bog'lanishda xatolik (HTTP {e.response.status_code})."}, ensure_ascii=False, indent=4)
    except requests.exceptions.RequestException as e:
        log.error(f"API request error for '{word}': {e}")
        return json.dumps({"error": f"Tarmoq xatoligi: API ga ulanib bo'lmadi."}, ensure_ascii=False, indent=4)
    except Exception as e:
        # Catch any other unexpected errors during processing
        log.exception(f"An unexpected error occurred in get_definitions for '{word}': {e}") # Log traceback
        return json.dumps({"error": f"Kutilmagan ichki xatolik yuz berdi."}, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    # Example usage for testing (requires logging setup)
    logging.basicConfig(level=logging.INFO)

    test_words = ['hello', 'test', 'inexistence', 'thisshouldnotexistxyz', '']

    for word_to_test in test_words:
        print(f"\n--- Testing '{word_to_test}' ---")
        definitions_json = get_definitions(word_to_test, 5)
        print(definitions_json)
        print("-" * 20)

    # Test with max_definitions=0
    print(f"\n--- Testing 'example' with max_definitions=0 ---")
    definitions_json = get_definitions('example', 0)
    print(definitions_json)
    print("-" * 20)