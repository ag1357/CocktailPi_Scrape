import requests
from bs4 import BeautifulSoup
import time
import json
import re
from dotenv import load_dotenv
import os

# Import the Google Generative AI library
import google.generativeai as genai

# --- Configuration ---
COCKTAIL_LIST_FILE = 'cocktail_list.json'
DETAILED_OUTPUT_JSON_FILE = 'cocktails_with_details_gemini.json' # New output file name

# --- Load environment variables ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env file. Please create a .env file and add your key.")
    exit()

# Configure the Google Generative AI client
genai.configure(api_key=GEMINI_API_KEY)

# Initialize the Gemini model
model = genai.GenerativeModel('models/gemini-1.5-pro-latest')

# --- Unit Conversion Data ---
UNIT_TO_ML = {
    'oz': 29.5735,
    'ml': 1.0,
    'cl': 10.0,
    'dash': 0.7,
    'dashes': 0.7,
    'drop': 0.05,
    'drops': 0.05,
    'tsp': 5.0, # teaspoon
    'teaspoon': 5.0,
    'tbs': 15.0, # tablespoon
    'tablespoon': 15.0,
    'part': 1.0, # "Part" is relative, so 1.0 here is a placeholder, will handle later in application
    'parts': 1.0,
    'shot': 44.0, # approx 1.5 oz
    'jigger': 44.0,
    'pony': 29.57, # approx 1 oz
    'cup': 236.588,
    'pint': 473.176,
    'quart': 946.353,
    'gallon': 3785.41,
    'barspoon': 5.0, # Approx 1 tsp
    'splash': 7.0, # Approx 1/4 oz
    'pinch': 0.3, # Approx 1/10 tsp
}

def calculate_unit_ml(amount, unit, ingredient_name):
    """
    Calculates amount in milliliters (ml) based on the extracted amount and unit.
    Returns None if amount is descriptive or unit is non-volumetric/unknown.
    Defaults to 5.0 ml if amount is None and unit is None, for likely liquid ingredients.
    """
    default_liquid_volume_ml = 5.0

    # List of ingredients that are explicitly liquids and should default to 5ml if no amount/unit
    # This list prioritizes defaulting for common liquid components.
    liquid_ingredients_to_default = [
        'vodka', 'gin', 'rum', 'tequila', 'whiskey', 'brandy', 'liqueur', 'vermouth', 'absinthe',
        'juice', 'syrup', 'soda', 'water', 'milk', 'cream', 'bitters', 'cordial', 'cava',
        'wine', 'champagne', 'beer', 'cider', 'cola', 'tonic', 'ginger ale', 'ginger beer',
        'cranberry', 'pineapple', 'grapefruit', 'orange juice', 'lemon-lime', 'blue curaçao',
        'cointreau', 'triple sec', 'amaretto', 'chartreuse', 'campari', 'aperol', 'kahlua',
        'frangelico', 'baileys', 'drambuie', 'schnapps', 'pimento dram', 'grenadine', 'falernum',
        'prosecco', 'sparkling wine' # Added some more common liquids
    ]

    # List of ingredients that are explicitly NON-LIQUID or qualitative amounts and should NOT default
    # This list is checked AFTER the liquid_ingredients_to_default.
    non_liquid_ingredients = [
        'slice', 'sprig', 'wedge', 'leaf', 'cubes', 'peel', 'strip', 'rim', 'top', 'fill',
        'egg', 'sugar', 'salt', 'pepper', 'nutmeg', 'cinnamon', 'berry', 'cherry', 'olive',
        'garnish', 'ice', 'chocolate', 'to taste', 'dust', 'powder', 'beans', 'fruit' 
    ]
    
    cleaned_ingredient_name = ingredient_name.lower().strip()

    is_amount_none = (amount is None or (isinstance(amount, str) and amount.lower() == 'none'))
    is_unit_none = (unit is None or (isinstance(unit, str) and unit.lower() == 'none'))

    if is_amount_none and is_unit_none:
        # 1. Check if it's a known liquid ingredient that should default
        if any(item in cleaned_ingredient_name for item in liquid_ingredients_to_default):
            return default_liquid_volume_ml
        # 2. Check if it's a known non-liquid ingredient that should NOT default
        elif any(item in cleaned_ingredient_name for item in non_liquid_ingredients):
            return None
        else:
            # 3. If it's neither explicitly liquid nor explicitly non-liquid,
            # we'll assume it's a liquid for safety and default.
            return default_liquid_volume_ml
    
    # If unit is explicitly "None" (from Gemini's output for non-volumetric things) AND amount is not a number
    # This handles cases like "top with soda" or "fill with water" where amount is missing, but unit is also not a number.
    if is_unit_none:
        return None

    # Original logic for numeric amounts and valid units
    try:
        numeric_amount = float(amount)
    except (ValueError, TypeError):
        return None # Amount is descriptive (e.g., "to taste", "fill with"), not a numerical value

    # If the amount is a range (e.g., "0.5-1 oz"), for simplicity, we return None for ml conversion
    if isinstance(numeric_amount, tuple) and len(numeric_amount) == 2:
        return None

    normalized_unit = str(unit).lower().strip()
    conversion_factor = UNIT_TO_ML.get(normalized_unit)

    if conversion_factor is not None:
        return numeric_amount * conversion_factor
    else:
        return None # Unit not found in conversion table or is non-volumetric

# --- Headers for requests (be a good citizen!) ---
HEADERS = {
    'User-Agent': 'MyCocktailPiScraper/1.0 (contact: your_email@example.com)', # IMPORTANT: Change to your email!
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

# --- Prompt Template for Gemini (Final Polish for Description) ---
GEMINI_PROMPT_TEMPLATE = """
You are an expert bartender and meticulous data extractor. You possess a deep understanding of cocktail creation, ingredients, and preparation methods. Your knowledge includes:

* **Ingredient Categories:** You understand the distinct roles of base spirits (e.g., rum, gin, whiskey, vodka, tequila), liqueurs (sweet, bitter, herbal), modifiers (e.g., vermouths, aperitifs, bitters), fresh juices (e.g., citrus, fruit), sweeteners (e.g., simple syrup, grenadine, honey, sugar), lengtheners (e.g., soda, tonic, sparkling wine), and garnishes (e.g., fruit peels, mint sprigs, olives).
* **Flavor and Balance:** You inherently grasp how different ingredients combine to form a cocktail's flavor profile (e.g., sweet, sour, bitter, spicy, earthy, herbaceous, fruity, savory, aromatic) and the principles of balancing these elements for a harmonious drink.
* **Standard Measures & Intent:** You recognize common bartender measures (e.g., oz, ml, cl, dash, drops, barspoon, jigger, shot, part) and can interpret the intent behind descriptive quantities like "to taste," "top with," "fill," "a few," or "splash."
* **Preparation Techniques:** You are intimately familiar with standard cocktail preparation methods including shaking (with or without ice, dry shake), stirring, building (in glass), muddling, layering, straining (fine or double), chilling, and proper garnishing. You understand that the preparation method impacts the final texture and temperature.
* **Ingredient Qualities:** You understand that "freshly squeezed" is often implied for juices unless otherwise specified, and that ingredients are typically of standard bar quality appropriate for cocktail mixing.
* **Common Substitutions/Variations:** You have a general awareness of common substitutions or variations that might be mentioned (e.g., different types of rum, specific brands of liqueurs).

Your primary task is to extract cocktail recipe information from the provided Wikipedia article text and structure it as a JSON object strictly following the specified format. This requires you to interpret and synthesize information like an experienced, human bartender would, even if explicit details are sparse or require inference from the context of typical cocktail construction.

Return the data as a JSON object with the following structure:
{{
  "description": "A concise, evocative description of the cocktail's flavor, aroma, and taste profile (max 500 characters). This field should always contain a sensory description. If you had to extrapolate the flavor profile from ingredients due to lack of explicit description in the text, append '(Flavor profile extrapolated from ingredients.)' to the end of your description.",
  "ingredients": [
    {{
      "amount": number or string (e.g., 1.5, 0.5, "to taste", "a few", "top with", "None" if quantity is not specified or irrelevant),
      "unit": string (e.g., "oz", "ml", "cl", "dash", "tsp", "tablespoon", "part", "None" if no specific volumetric unit is given or it's a non-liquid measure like "slice", "sprig"),
      "name": string (cleaned ingredient name, e.g., "gin", "lemon juice", "sugar syrup")
    }}
  ],
  "preparation": [
    "step 1 text",
    "step 2 text"
  ]
}}

Guidelines for Extraction:
- **Description:** This is crucial. Always provide a concise, evocative description of the cocktail's flavor, aroma, and taste profile. Prioritize sensory details. If explicit sensory descriptions are not in the text, you MUST extrapolate based on the typical profiles of the ingredients. If you had to extrapolate the flavor profile due to a lack of explicit information, append '(Flavor profile extrapolated from ingredients.)' to the end of your generated description. Max 500 characters.
- **Ingredients:**
    - Extract 'amount' accurately if provided. If a quantity is descriptive (e.g., "to taste", "top with", "a few", "enough", "splash"), return that descriptive phrase as a string for 'amount'. If no quantity (numerical or descriptive) is mentioned but it's a required ingredient, use "None" for 'amount'.
    - For 'unit', use standard volumetric abbreviations (oz, ml, cl, dash, tsp, tbsp, part, dashes, drops, barspoon, splash) where applicable. If the quantity is non-volumetric (e.g., "slice", "sprig", "wedge", "leaf", "cubes", "peel") or no unit is given, use "None".
    - Clean ingredient 'name': remove descriptive adjectives like "freshly squeezed", "dry", "sweet", "good quality", "premium", "London Dry". Remove parenthetical notes.
    - If an ingredient is explicitly described as "for garnish" or "optional", set 'unit' to "None'. If a specific number (e.g., "1" slice) is given, use that as 'amount'; otherwise, if it's purely decorative, use "None" for 'amount'.
    - Handle "parts" notation: e.g., "1 part gin" -> amount: 1, unit: "part".
- **Preparation:**
    - Keep preparation steps concise and ordered.
- **General:**
    - If a section (ingredients or preparation) is not found or is empty, return an empty array for that field.
    - If the text is not a recipe, return empty arrays for ingredients and preparation, and an empty description.
    - Ensure the output is *only* the JSON object, no extra text or markdown.

Here is the Wikipedia article content:
---
{article_text}
---
"""

def extract_content_for_gemini(soup, section_id=None):
    """
    Extracts relevant text content for Gemini from the parsed HTML.
    Prioritizes infobox, then all main content sections.
    """
    sections = []

    # Try to get content from Infobox
    infobox = soup.find('table', class_='infobox')
    if infobox:
        infobox_text = infobox.get_text(separator='\n', strip=True)
        sections.append("Infobox Content:\n" + infobox_text)

    # Get content from the main article body by grabbing most block elements
    main_content_div = soup.find('div', class_='mw-parser-output')
    if main_content_div:
        content_elements = []
        # Find all common block elements that usually contain meaningful text
        # recursive=True is default, but explicitly setting to ensure deep search
        for element in main_content_div.find_all(['p', 'ul', 'ol', 'h2', 'h3', 'h4', 'h5', 'h6', 'div']): # Added 'div' to catch more structured text
            # Skip known non-content elements (navigation, references, templates, etc.)
            classes_to_skip = ['mw-references-columns', 'reflist', 'navbox', 'toc', 
                               'authority-control', 'hatnote', 'metadata', 'printfooter',
                               'portalbox', 'noprint', 'sister-project'] # Added more classes to skip
            if any(cls in element.get('class', []) for cls in classes_to_skip):
                continue
            
            # Skip some specific divs if they appear to be wrappers for other non-content things
            if element.name == 'div' and (element.get('role') == 'navigation' or element.get('id') in ['mw-content-text', 'siteSub', 'jump-to-nav']):
                continue

            # Process text from elements that are not headings (unless it's a direct recipe heading)
            if element.name not in ['h2', 'h3', 'h4', 'h5', 'h6']:
                text = element.get_text(separator='\n', strip=True)
                if text:
                    content_elements.append(text)
            else: # For headings, just get their text, as they provide context
                text = element.get_text(separator='\n', strip=True)
                if text:
                    content_elements.append(f"## {text}") # Add markdown for headings to give structure hint to Gemini

        full_main_content = '\n\n'.join(content_elements)
        if full_main_content:
            sections.append("Main article content:\n" + full_main_content)

    # Combine all extracted sections
    full_text = '\n\n'.join(s for s in sections if s.strip())
    
    # Simple cleanup before sending to Gemini
    full_text = re.sub(r'\[.*?\]', '', full_text) # Remove wiki references like [1]
    full_text = re.sub(r'\n{2,}', '\n\n', full_text) # Reduce multiple newlines
    full_text = full_text.strip()

    # Limit text length to avoid token limits for very long pages
    MAX_TEXT_LENGTH = 15000 
    if len(full_text) > MAX_TEXT_LENGTH:
        full_text = full_text[:MAX_TEXT_LENGTH] + "\n[...content truncated due to length...]" # Add a note about truncation

    return full_text


def scrape_cocktail_details(cocktail_info):
    """
    Fetches details for a single cocktail and uses Gemini for extraction.
    """
    url = cocktail_info['url']
    name = cocktail_info['name']
    print(f"  Scraping details for '{name}' from {url}...")
    
    details = {
        'name': name,
        'url': url,
        'description': '',
        'ingredients': [],
        'preparation': []
    }

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  Error fetching {url}: {e}")
        return details

    soup = BeautifulSoup(response.text, 'html.parser')

    # Determine if there's a section ID in the URL
    section_id = url.split('#')[-1] if '#' in url else None

    # Extract relevant plain text content for Gemini
    article_text_for_gemini = extract_content_for_gemini(soup, section_id)

    if not article_text_for_gemini.strip():
        print(f"  Warning: No relevant content found for {name} to send to Gemini.")
        details['notes'] = details.get('notes', []) + ["No relevant content found on page."]
        return details # Return empty details if no content

    # --- Make Gemini API Call ---
    try:
        prompt = GEMINI_PROMPT_TEMPLATE.format(article_text=article_text_for_gemini)
        
        gemini_response = model.generate_content(prompt)
        
        # Attempt to parse the JSON response
        response_text = gemini_response.text.strip()
        
        # First, try to strip off markdown JSON fences if present
        if response_text.startswith("```json") and response_text.endswith("```"):
            json_string = response_text[7:-3].strip()
        else:
            json_string = response_text

        extracted_data = {} # Initialize as empty dictionary

        try:
            # If json_string is empty, json.loads('') will raise a ValueError.
            # Handle this gracefully.
            if json_string:
                extracted_data = json.loads(json_string)
            else:
                print(f"  Warning: Gemini returned empty or whitespace-only response for {name}.")
                details['notes'] = details.get('notes', []) + ["Gemini returned empty response."]

        except ValueError as ve:
            print(f"  Error parsing Gemini JSON response for {name}: {ve}")
            print(f"  Raw Gemini response snippet: {json_string[:200]}...") # Print a snippet for debugging
            details['notes'] = details.get('notes', []) + [f"Gemini JSON parse error: {ve}"]
        except Exception as e:
            # Catch any other unexpected parsing errors
            print(f"  Unexpected error during JSON parsing for {name}: {e}")
            details['notes'] = details.get('notes', []) + [f"Unexpected JSON parse error: {e}"]

        # Populate details from extracted_data (will be empty dict if parsing failed)
        details['description'] = extracted_data.get('description', '')
        details['ingredients'] = extracted_data.get('ingredients', [])
        details['preparation'] = extracted_data.get('preparation', [])

        # --- Post-processing for Description: Conditionally remove "extrapolated" note ---
        description_text = details['description']
        extrapolated_note = "(Flavor profile extrapolated from ingredients.)"
        
        # Check if the note exists at the end of the description
        if description_text.endswith(extrapolated_note):
            # Get the description part *before* the note
            base_description = description_text[:-len(extrapolated_note)].strip()
            
            # Heuristic: If the base description is reasonably long (e.g., > 75 characters)
            # then remove the extrapolation note. You can adjust this limit.
            if len(base_description) > 75:
                details['description'] = base_description
            # Else (if base_description is short), keep the full description including the note.
        # --- End Post-processing for Description ---


        # --- Post-processing: Calculate unit_ml for ingredients ---
        for ingredient in details['ingredients']:
            amount = ingredient.get('amount')
            unit = ingredient.get('unit')
            name = ingredient.get('name', '') # Get the ingredient name
            ingredient['unit_ml'] = calculate_unit_ml(amount, unit, name) # Pass the name to the function


    except Exception as e:
        print(f"  Error during Gemini API call for {name}: {e}")
        details['notes'] = details.get('notes', []) + [f"Gemini API call failed: {e}"]
        # Fallback to empty ingredients/preparation if API call fails

    return details

# --- Main execution ---
if __name__ == "__main__":
    try:
        with open(COCKTAIL_LIST_FILE, 'r', encoding='utf-8') as f:
            cocktail_list = json.load(f)
    except FileNotFoundError:
        print(f"Error: {COCKTAIL_LIST_FILE} not found. Run scrape_cocktails.py first.")
        exit()

    all_cocktail_details = []
    
    # Process all cocktails or a test limit
    test_limit = 20 # Process first 20 for initial test with Gemini
    cocktails_to_process = cocktail_list[:test_limit]

    # For full run: uncomment the line below and comment out the test_limit lines
    # cocktails_to_process = cocktail_list

    for i, cocktail_info in enumerate(cocktails_to_process):
        print(f"Processing {i+1}/{len(cocktails_to_process)}: {cocktail_info['name']}")
        details = scrape_cocktail_details(cocktail_info)
        all_cocktail_details.append(details)
        time.sleep(1.5) # Increased delay to be polite to Gemini API and avoid rate limits

    print(f"\nScraping complete for {len(all_cocktail_details)} cocktails.")

    with open(DETAILED_OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_cocktail_details, f, indent=4, ensure_ascii=False)
    print(f"Detailed cocktail data saved to {DETAILED_OUTPUT_JSON_FILE}")
