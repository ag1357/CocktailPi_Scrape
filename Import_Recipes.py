import requests
import json
import time
from collections import defaultdict

# --- Configuration ---
BASE_URL = 'http://192.168.000.000' # !!! VERIFY THIS IP ADDRESS IS CORRECT FOR YOUR COCKTAILPI SERVER !!!
USERNAME = 'Admin'
PASSWORD = '123456'
COCKTAILS_DATA_FILE = 'cocktails_with_details_gemini.json'

# --- API Endpoints ---
LOGIN_URL = f"{BASE_URL}/api/auth/login"
INGREDIENT_API_URL = f"{BASE_URL}/api/ingredient/"
GLASS_API_URL = f"{BASE_URL}/api/glass/"
CATEGORY_API_URL = f"{BASE_URL}/api/category/"
RECIPE_API_URL = f"{BASE_URL}/api/recipe/"
CREATE_INGREDIENT_URL = f"{BASE_URL}/api/ingredient/" # Endpoint to create new ingredients

# --- Global Session and Token ---
session = requests.Session()
access_token = None
token_type = 'Bearer'

# --- Ingredient Classification and Mapping Rules ---
# This is a key part of smart mapping.
# The keys are keywords found in scraped ingredient names.
# The values are the target names of CocktailPi ingredient *groups* or *specific ingredients*
# you want to map to. Order matters for specific vs. general (e.g., 'creme de cacao' before 'liqueur').
# IMPORTANT: Ensure these values (the right side of the colon) exist as exact lowercase names
# in your CocktailPi's ingredient list (either as groups or individual ingredients).
INGREDIENT_CLASSIFICATION_RULES = {
    # Spirits
    'vodka': 'vodka',
    'gin': 'gin',
    'rum': 'rum', # General rum group
    'white rum': 'white rum',
    'gold rum': 'gold rum',
    'aged rum': 'aged rum',
    'tequila': 'tequila',
    'mezcal': 'mezcal',
    'whiskey': 'whiskey', # General whiskey group
    'bourbon': 'bourbon',
    'rye': 'rye whiskey',
    'scotch': 'scotch',
    'brandy': 'brandy', # General brandy group
    'cognac': 'cognac',
    'pisco': 'pisco', # Specific spirit, if not under 'brandy' group
    'dry gin': 'gin', # map specific gin types to general gin

    # Liqueurs (more specific first)
    'blue curaçao': 'blue curaçao', # If you have it specific
    'creme de cacao': 'chocolate liqueur', # Maps to a specific liqueur or a 'sweet liqueurs' group
    'creme de cassis': 'cassis liqueur',
    'coffee liqueur': 'coffee liqueur',
    'orange liqueur': 'orange liqueur', # For Triple Sec, Cointreau, Grand Marnier
    'triple sec': 'orange liqueur',
    'cointreau': 'orange liqueur',
    'grand marnier': 'orange liqueur',
    'amaretto': 'amaretto',
    'peach schnapps': 'peach schnapps',
    'elderflower liqueur': 'elderflower liqueur',
    'absinthe': 'absinthe',
    'liqueur': 'liqueur', # General fallback for any other liqueur
    'aperol': 'aperol',
    'campari': 'campari',
    'schnapps': 'schnapps', # General schnapps (e.g., Apple schnapps)

    # Vermouths & Amari
    'sweet vermouth': 'sweet vermouth',
    'dry vermouth': 'dry vermouth',
    'blanc vermouth': 'blanc vermouth',
    'vermouth': 'vermouth', # General fallback for any vermouth
    'amaro': 'amaro', # General amaro group
    'fernet': 'fernet',
    'lillet': 'lillet',

    # Juices
    'lemon juice': 'lemon juice',
    'lime juice': 'lime juice',
    'orange juice': 'orange juice',
    'cranberry juice': 'cranberry juice',
    'pineapple juice': 'pineapple juice',
    'grapefruit juice': 'grapefruit juice',
    'passion fruit juice': 'passion fruit juice',
    'apple juice': 'apple juice',
    'juice': 'juice', # General fallback for any other juice

    # Syrups
    'simple syrup': 'simple syrup',
    'sugar syrup': 'simple syrup',
    'orgeat': 'orgeat syrup',
    'grenadine': 'grenadine',
    'honey syrup': 'honey syrup',
    'agave nectar': 'agave nectar',
    'syrup': 'syrup', # General fallback for any other syrup
    'honey': 'honey syrup', # Map raw honey to honey syrup if dispensable

    # Bitters
    'bitters': 'bitters', # General bitters group
    'angostura bitters': 'bitters',
    'orange bitters': 'orange bitters',
    'peychaud\'s bitters': 'peychauds bitters',

    # Mixers (often carbonated or non-alcoholic liquids)
    'soda water': 'soda water',
    'club soda': 'soda water',
    'tonic water': 'tonic water',
    'cola': 'cola',
    'sprite': 'lemon-lime soda',
    'lemon-lime': 'lemon-lime soda',
    'ginger ale': 'ginger ale',
    'ginger beer': 'ginger beer',
    'milk': 'milk',
    'cream': 'cream',
    'condensed milk': 'condensed milk',

    # Wines (if dispensable/categorized)
    'sherry': 'sherry',
    'prosecco': 'prosecco',
    'champagne': 'champagne',
    'cava': 'cava',
    'dry white wine': 'dry white wine',

    # Add more rules as needed based on your scraped data and CocktailPi setup
    # Make sure keys are lowercase and values are exact lowercase CocktailPi names.
}

# --- Ingredients that are typically garnishes or manual additions, not auto-created ---
# This list prevents the script from trying to create things like 'ice cubes' or 'mint leaves' as ingredients.
COMMON_IMPLIED_ELEMENTS = [
    'ice', 'cubes', 'garnish', 'sprig', 'slice', 'wedge', 'peel', 'leaf',
    'cherry', 'olive', 'salt', 'sugar', 'nutmeg', 'cinnamon', 'to taste',
    'fill', 'top with', 'splash of', 'none', 'rim', 'dashes', 'drops', 'twist',
    'dash', 'drop', 'muddle', 'muddled', 'fresh', 'dry', 'whole', 'powder',
    'water', 'hot water', 'coffee', 'tea', 'egg white', 'egg yolk', # These are often explicitly listed but are manual
    'mint', 'lime', 'lemon', # If these appear alone, assume they are garnish/manual fruit
    'orange', 'grapefruit', 'pineapple', 'cranberry', 'apple', 'passion fruit' # As whole fruits
]

# --- Default values for auto-created ingredients ---
# These will be created as manual ingredients (not on pump) by default
AUTO_CREATE_DEFAULTS = {
    'type': 'manual', # 'automated', 'manual', 'group'
    'inBar': False,
    'onPump': False, # This will be conditionally used
    'alcoholContent': 0 # Default to 0, can be adjusted manually in CocktailPi later
}

# --- Global variable to store the ID of a default parent group for auto-created ingredients ---
# We will populate this during fetch_cocktailpi_data()
DEFAULT_PARENT_GROUP_ID = None

# --- Function to make authenticated GET requests ---
def authenticated_get(endpoint, params=None):
    if not access_token:
        print("Error: Not logged in. Cannot make authenticated request.")
        return None
    
    url = f"{BASE_URL}/api/{endpoint}"
    headers = {
        'Authorization': f"{token_type} {access_token}",
        'Accept': 'application/json'
    }
    try:
        response = session.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"Error fetching {endpoint}: HTTP Error {e.response.status_code}. Response: {e.response.text}")
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to CocktailPi at {BASE_URL} while fetching {endpoint}.")
    except Exception as e:
        print(f"An unexpected error occurred fetching {endpoint}: {e}")
    return None

# --- Function to create a new ingredient in CocktailPi ---
def create_cocktailpi_ingredient(name, ingredient_type='manual', alcohol_content=0, in_bar=False, on_pump=False, parent_group_id=None):
    if not access_token:
        print("Error: Not logged in. Cannot create ingredient.")
        return None

    print(f"  Attempting to create new CocktailPi ingredient: '{name}'")
    
    ingredient_payload = {
        'name': name,
        'type': ingredient_type,
        'alcoholContent': alcohol_content,
        'inBar': in_bar,
    }
    
    # Only include 'onPump' in the payload if the ingredient type is 'automated'.
    if ingredient_type == 'automated':
        ingredient_payload['onPump'] = on_pump

    # IMPORTANT ADDITION: Include parentGroupId if provided
    if parent_group_id:
        ingredient_payload['parentGroupId'] = parent_group_id

    # --- ADDED DEBUGGING HERE ---
    print(f"  DEBUG: Sending ingredient creation payload: {json.dumps(ingredient_payload, indent=2)}")
    # --- END DEBUGGING ---

    headers = {
        'Authorization': f"{token_type} {access_token}",
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    try:
        response = session.post(CREATE_INGREDIENT_URL, json=ingredient_payload, headers=headers)
        response.raise_for_status()
        new_ingredient = response.json()
        print(f"  Successfully created ingredient '{name}' with ID: {new_ingredient['id']}")
        return new_ingredient
    except requests.exceptions.HTTPError as e:
        print(f"  DEBUG: Full HTTP error response for '{name}': {e.response.text}") # Print full error response
        if e.response.status_code == 409: # Conflict - ingredient name already exists
            print(f"  Info: Ingredient '{name}' already exists on CocktailPi (409 Conflict). Skipping creation.")
        else:
            print(f"  Error creating ingredient '{name}': HTTP Error {e.response.status_code}. Response: {e.response.text}")
    except Exception as e:
        print(f"  An unexpected error occurred creating ingredient '{name}': {e}")
    return None


# --- Main login function ---
def login():
    global access_token, token_type
    print("Attempting to log in to CocktailPi API...")
    login_payload = {
        'username': USERNAME,
        'password': PASSWORD,
        'remember': False
    }
    login_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    try:
        login_response = session.post(LOGIN_URL, json=login_payload, headers=login_headers)
        login_response.raise_for_status()
        print("Successfully logged in!")
        login_json = login_response.json()
        access_token = login_json.get('accessToken')
        token_type = login_json.get('tokenType', 'Bearer')
        if access_token:
            print(f"JWT access token obtained ({token_type}): {access_token[:20]}...")
            return True
        else:
            print("Error: No 'accessToken' found in login response. Cannot proceed.")
            print(f"Full Login Response: {json.dumps(login_json, indent=2)}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to CocktailPi at {BASE_URL}. Is CocktailPi running?")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"Login failed: HTTP Error {e.response.status_code}. Response: {e.response.text}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during login: {e}")
        return False

# --- Fetch CocktailPi's existing data (Ingredients, Glasses, Categories) ---
def fetch_cocktailpi_data():
    global DEFAULT_PARENT_GROUP_ID # Declare global to modify it

    print("\nFetching existing CocktailPi ingredients...")
    # Include all types (automated, manual, group) and all 'inBar' statuses for mapping
    ingredient_params = {
        'filterManualIngredients': 'true',
        'filterAutomaticIngredients': 'true',
        'filterGroups': 'true',
        'inBar': 'false' 
    }
    ingredients_data = authenticated_get('ingredient/', params=ingredient_params)
    
    ingredient_name_to_id = {}
    group_name_to_id = {} # Store groups separately for default parent ID
    if ingredients_data:
        for item in ingredients_data:
            lower_name = item['name'].lower().strip()
            ingredient_name_to_id[lower_name] = item['id']
            if item['type'] == 'group':
                group_name_to_id[lower_name] = item['id']

    print(f"Found {len(ingredient_name_to_id)} mappable ingredients/groups on CocktailPi.")
    
    # Attempt to find a suitable default parent group ID
    if group_name_to_id:
        if 'other liquids' in group_name_to_id:
            DEFAULT_PARENT_GROUP_ID = group_name_to_id['other liquids']
            print(f"Found 'Other Liquids' group (ID: {DEFAULT_PARENT_GROUP_ID}) for default parent.")
        elif 'other' in group_name_to_id: # Fallback if 'other liquids' doesn't exist
            DEFAULT_PARENT_GROUP_ID = group_name_to_id['other']
            print(f"Found 'Other' group (ID: {DEFAULT_PARENT_GROUP_ID}) for default parent.")
        elif 'manual ingredients' in group_name_to_id:
            DEFAULT_PARENT_GROUP_ID = group_name_to_id['manual ingredients']
            print(f"Found 'Manual Ingredients' group (ID: {DEFAULT_PARENT_GROUP_ID}) for default parent.")
        else: # Take the first available group if no specific ones are found
            DEFAULT_PARENT_GROUP_ID = list(group_name_to_id.values())[0]
            print(f"Using first available group '{list(group_name_to_id.keys())[0]}' (ID: {DEFAULT_PARENT_GROUP_ID}) as default parent.")
    else:
        print("Warning: No ingredient groups found on CocktailPi. Auto-creation of ingredients may fail without a parent group ID.")

    print("Fetching existing CocktailPi glasses...")
    glasses_data = authenticated_get('glass/')
    glass_name_to_id = {item['name'].lower().strip(): item['id'] for item in glasses_data} if glasses_data else {}
    print(f"Found {len(glass_name_to_id)} glasses on CocktailPi.")

    print("Fetching existing CocktailPi categories...")
    categories_data = authenticated_get('category/')
    category_name_to_id = {item['name'].lower().strip(): item['id'] for item in categories_data} if categories_data else {}
    print(f"Found {len(category_name_to_id)} categories on CocktailPi.")

    return ingredient_name_to_id, glass_name_to_id, category_name_to_id

# --- Function to build the recipe payload for CocktailPi ---
def build_cocktailpi_recipe_payload(scraped_recipe, ingredient_mapping, default_glass_id, default_category_id):
    recipe_name = scraped_recipe.get('name')
    description = scraped_recipe.get('description', '')
    
    production_steps = []
    dispensable_ingredients = []
    
    # Iterate through ingredients from the scraped recipe
    for ing in scraped_recipe.get('ingredients', []):
        ing_name_raw = ing.get('name', '')
        ing_name_lower = ing_name_raw.lower().strip()
        ing_amount_ml = ing.get('unit_ml')
        
        cocktailpi_ingredient_id = None
        mapped_cocktailpi_name = None # Store the name we mapped to

        # --- Check if it's a common implied element (garnish, non-liquid, etc.) ---
        # This prevents auto-creation of things like 'ice cubes' or 'mint leaves' as ingredients.
        # It also prevents adding explicit instructions for common terms.
        if any(elem == ing_name_lower or (elem in ing_name_lower and len(ing_name_lower) - len(elem) < 3) for elem in COMMON_IMPLIED_ELEMENTS):
            if ing_amount_ml is not None and ing_amount_ml > 0:
                print(f"  Info: '{ing_name_raw}' has liquid amount but is considered an implied/non-dispensable element. Skipping for dispense.")
            else:
                print(f"  Info: Skipping implied non-dispensable ingredient '{ing_name_raw}'.")
            
            # Add as a written instruction if it's not a generic instruction itself
            is_generic_instruction_term = any(elem == ing_name_lower for elem in ['ice', 'sugar', 'salt', 'water', 'none']) # Add other generic terms if needed
            
            if not is_generic_instruction_term:
                instruction_message_parts = []
                # Only add amount/unit if they're not part of the common elements list and are present
                if ing.get('amount') is not None and str(ing.get('amount')).lower().strip() not in COMMON_IMPLIED_ELEMENTS and str(ing.get('amount')).lower().strip() != 'none':
                    instruction_message_parts.append(str(ing['amount']))
                if ing.get('unit') is not None and str(ing.get('unit')).lower().strip() not in COMMON_IMPLIED_ELEMENTS and str(ing.get('unit')).lower().strip() != 'none':
                    instruction_message_parts.append(str(ing['unit']))
                
                instruction_message_parts.append(ing_name_raw) # Always include the ingredient name

                if instruction_message_parts:
                    production_steps.append({
                        "type": "writtenInstruction",
                        "message": f"Add {' '.join(instruction_message_parts).strip()}"
                    })
            continue # Move to next ingredient


        # --- Mapping Logic Hierarchy ---

        # 1. Check for a direct match in CocktailPi's current ingredients (exact name)
        if ing_name_lower in ingredient_mapping:
            cocktailpi_ingredient_id = ingredient_mapping[ing_name_lower]
            mapped_cocktailpi_name = ing_name_lower
            print(f"  Info: Direct matched '{ing_name_raw}' to CocktailPi ingredient '{mapped_cocktailpi_name}'.")

        # 2. Apply INGREDIENT_CLASSIFICATION_RULES (Smart Group/Specific Mapping)
        # This attempts to map to a broader category/group in CocktailPi
        if not cocktailpi_ingredient_id:
            for keyword, target_cp_name in INGREDIENT_CLASSIFICATION_RULES.items():
                if keyword in ing_name_lower:
                    if target_cp_name in ingredient_mapping:
                        cocktailpi_ingredient_id = ingredient_mapping[target_cp_name]
                        mapped_cocktailpi_name = target_cp_name
                        print(f"  Info: Classified '{ing_name_raw}' as '{keyword}', mapped to CocktailPi ingredient/group '{target_cp_name}'.")
                        break # Found a classification match, no need to check other rules for this ingredient

        # 3. Fallback to fuzzy matching (simple 'in' check, less reliable but catches some)
        if not cocktailpi_ingredient_id:
            for cp_name, cp_id in ingredient_mapping.items():
                if (ing_name_lower in cp_name or cp_name in ing_name_lower) and \
                   (len(ing_name_lower) > 3 or len(cp_name) > 3): # Avoid matching very short, generic words
                    cocktailpi_ingredient_id = cp_id
                    mapped_cocktailpi_name = cp_name
                    print(f"  Info: Fuzzy matched '{ing_name_raw}' to CocktailPi ingredient '{mapped_cocktailpi_name}'.")
                    break
        
        # --- Handle Unmapped Liquid Ingredients: Auto-Create if Applicable ---
        if ing_amount_ml is not None and ing_amount_ml > 0 and not cocktailpi_ingredient_id:
            # The name for auto-creation should be the original scraped name (raw case)
            ingredient_to_create_name = ing_name_raw.strip()

            if DEFAULT_PARENT_GROUP_ID is None:
                print(f"  Warning: Ingredient '{ing_name_raw}' could not be matched. Auto-creation skipped: No default parent group ID found.")
            else:
                print(f"  Attempting to auto-create missing liquid ingredient '{ingredient_to_create_name}'...")
                new_cp_ingredient = create_cocktailpi_ingredient(
                    ingredient_to_create_name, # Use the raw name for creation
                    ingredient_type=AUTO_CREATE_DEFAULTS['type'],
                    alcohol_content=AUTO_CREATE_DEFAULTS['alcoholContent'],
                    in_bar=AUTO_CREATE_DEFAULTS['inBar'],
                    on_pump=AUTO_CREATE_DEFAULTS['onPump'],
                    parent_group_id=DEFAULT_PARENT_GROUP_ID # Pass the default parent group ID
                )
                if new_cp_ingredient:
                    cocktailpi_ingredient_id = new_cp_ingredient['id']
                    # Add newly created ingredient to our local map for subsequent recipes in this run
                    ingredient_mapping[new_cp_ingredient['name'].lower().strip()] = cocktailpi_ingredient_id
                    mapped_cocktailpi_name = new_cp_ingredient['name'].lower().strip()
                else:
                    print(f"  Warning: Ingredient '{ing_name_raw}' has a liquid amount but could not be matched/created. Will not be dispensed.")
        elif ing_amount_ml is not None and ing_amount_ml > 0 and not cocktailpi_ingredient_id:
             # This branch is for cases where auto-creation was deemed unsuitable (e.g., in COMMON_IMPLIED_ELEMENTS)
             print(f"  Warning: Ingredient '{ing_name_raw}' has a liquid amount but could not be matched. Not suitable for auto-creation. Will not be dispensed.")


        # --- Add to dispensable ingredients or written instructions ---
        if ing_amount_ml is not None and ing_amount_ml > 0 and cocktailpi_ingredient_id:
            # If it's a liquid amount AND we found/created a CocktailPi ingredient ID, add to dispensable list
            dispensable_ingredients.append({
                "amount": round(ing_amount_ml),
                "scale": True,
                "boostable": True,
                "ingredientId": cocktailpi_ingredient_id
            })
        elif not cocktailpi_ingredient_id: # If still no ID for this ingredient, add as written instruction
            # This 'else' covers cases where it's a liquid ingredient but couldn't be matched/created,
            # or it's a non-liquid ingredient that wasn't covered by COMMON_IMPLIED_ELEMENTS
            instruction_message_parts = []
            if ing.get('amount') is not None and str(ing.get('amount')).lower().strip() not in COMMON_IMPLIED_ELEMENTS and str(ing.get('amount')).lower().strip() != 'none':
                instruction_message_parts.append(str(ing['amount']))
            if ing.get('unit') is not None and str(ing.get('unit')).lower().strip() not in COMMON_IMPLIED_ELEMENTS and str(ing.get('unit')).lower().strip() != 'none':
                instruction_message_parts.append(str(ing['unit']))
            
            # Ensure the ingredient name itself is not just a general instruction (like 'ice')
            if ing_name_lower not in [elem.lower() for elem in COMMON_IMPLIED_ELEMENTS]:
                instruction_message_parts.append(ing_name_raw)

            if instruction_message_parts:
                production_steps.append({
                    "type": "writtenInstruction",
                    "message": f"Add {' '.join(instruction_message_parts).strip()}"
                })
            else:
                # This case should ideally be caught by COMMON_IMPLIED_ELEMENTS check earlier
                print(f"  Info: No meaningful instruction for '{ing_name_raw}', skipping as written instruction.")


    # Add all dispensable ingredients as one step
    if dispensable_ingredients:
        production_steps.append({
            "type": "addIngredients",
            "stepIngredients": dispensable_ingredients
        })
    
    # Add preparation steps as written instructions
    for step in scraped_recipe.get('preparation', []):
        if step.strip():
            production_steps.append({
                "type": "writtenInstruction",
                "message": step.strip()
            })
    
    # Fallback if no steps generated
    if not production_steps:
        production_steps.append({
            "type": "writtenInstruction",
            "message": "No specific instructions found for this recipe. Combine ingredients and serve."
        })

    payload = {
        "name": recipe_name,
        "ownerId": 1, # Default owner is usually 'Bar' with ID 1
        "description": description,
        "productionSteps": production_steps,
        "defaultGlassId": default_glass_id,
        "categoryIds": [default_category_id] # Temporarily still using default, will enhance soon
    }
    
    return payload

# --- Main execution flow ---
if __name__ == '__main__':
    if not login():
        exit()

    # ingredient_map now also includes group_name_to_id for default parent group finding
    ingredient_map, glass_map, category_map = fetch_cocktailpi_data()

    if not ingredient_map:
        print("Could not retrieve CocktailPi ingredients. Cannot proceed with recipe import.")
        exit()
    
    # Default Glass ID (can be made dynamic later based on volume)
    DEFAULT_GLASS_ID = 1 # Fallback to 1 if no common glass names found
    if glass_map:
        # Prioritize common cocktail glasses by name
        DEFAULT_GLASS_ID = glass_map.get('cocktail glass',
                             glass_map.get('coupe',
                             glass_map.get('old fashioned glass',
                             glass_map.get('highball glass',
                             glass_map.get('shot glass', list(glass_map.values())[0] if glass_map else 1)))))
    print(f"Using default glass ID: {DEFAULT_GLASS_ID} (from map or fallback)")


    # Default Category ID (will be replaced by intelligent categorization)
    DEFAULT_CATEGORY_ID = 7 # Fallback to 7 (often 'Other' or 'Classic')
    if category_map:
        # Prioritize 'Classic' or 'Other'
        DEFAULT_CATEGORY_ID = category_map.get('classic',
                                   category_map.get('other',
                                   list(category_map.values())[0] if category_map else 7))
    print(f"Using default category ID: {DEFAULT_CATEGORY_ID} (from map or fallback)")


    try:
        with open(COCKTAILS_DATA_FILE, 'r', encoding='utf-8') as f:
            cocktails_to_import = json.load(f)
        print(f"\nLoaded {len(cocktails_to_import)} recipes from {COCKTAILS_DATA_FILE}")
    except FileNotFoundError:
        print(f"Error: {COCKTAILS_DATA_FILE} not found. Please run scrape_cocktail_details.py first.")
        exit()
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {COCKTAILS_DATA_FILE}. Check file content.")
        exit()
    except Exception as e:
        print(f"An unexpected error occurred loading {COCKTAILS_DATA_FILE}: {e}")
        exit()

    # --- Fetch existing recipe names to prevent duplicates ---
    print("\nFetching existing recipes to check for duplicates...")
    existing_recipes_data = authenticated_get('recipe/')

    existing_recipe_names = set()
    if existing_recipes_data and isinstance(existing_recipes_data, dict) and 'content' in existing_recipes_data:
        for recipe_dict in existing_recipes_data['content']:
            if isinstance(recipe_dict, dict) and 'name' in recipe_dict:
                existing_recipe_names.add(recipe_dict['name'].lower().strip())
        print(f"  Detected existing recipes as a dictionary with 'content' key.")
    else:
        print(f"  Warning: Unexpected structure for existing recipes data. Cannot check for duplicates effectively. Data type: {type(existing_recipes_data)}")
        # If it's not the expected dictionary structure, existing_recipe_names will remain empty,
        # which means all recipes will be attempted for import, potentially leading to duplicates.

    print(f"Found {len(existing_recipe_names)} existing recipes on CocktailPi.")


    print("\n--- Starting Recipe Import ---")
    imported_count = 0
    skipped_count = 0
    duplicate_count = 0

    for i, cocktail in enumerate(cocktails_to_import):
        cocktail_name = cocktail.get('name', 'Unnamed Recipe').strip()
        cocktail_name_lower = cocktail_name.lower()
        print(f"\nProcessing recipe {i+1}/{len(cocktails_to_import)}: '{cocktail_name}'")

        if not cocktail_name or (not cocktail.get('ingredients') and not cocktail.get('preparation')):
            print(f"  Skipping '{cocktail_name}' - no valid name or no ingredients/preparation found in scraped data.")
            skipped_count += 1
            continue
        
        if cocktail_name_lower in existing_recipe_names:
            print(f"  Skipping '{cocktail_name}' - Recipe already exists (duplicate detected).")
            duplicate_count += 1
            continue

        cocktailpi_payload = build_cocktailpi_recipe_payload(
            cocktail, ingredient_map, DEFAULT_GLASS_ID, DEFAULT_CATEGORY_ID
        )

        # Check if the generated payload has any meaningful steps before attempting to import
        has_meaningful_steps = False
        for step in cocktailpi_payload['productionSteps']:
            if step['type'] == 'addIngredients' and step['stepIngredients']:
                has_meaningful_steps = True
                break
            if step['type'] == 'writtenInstruction' and step['message'] != "No specific instructions found for this recipe. Combine ingredients and serve.":
                has_meaningful_steps = True
                break
        
        if not has_meaningful_steps:
            print(f"  Skipping '{cocktail_name}' - generated payload contains no meaningful dispense or instruction steps.")
            skipped_count += 1
            continue

        recipe_json_string = json.dumps(cocktailpi_payload)
        files_to_send = {
            'recipe': ('blob', recipe_json_string, 'application/json')
        }

        print(f"  Attempting to import '{cocktail_name}'...")
        try:
            import_headers = {
                'Authorization': f"{token_type} {access_token}",
                'Accept': 'application/json'
            }
            import_response = session.post(RECIPE_API_URL, files=files_to_send, headers=import_headers)
            
            if import_response.status_code in [200, 201]:
                print(f"  Successfully imported '{cocktail_name}'!")
                imported_count += 1
                existing_recipe_names.add(cocktail_name_lower) # Add to prevent duplicates within the same run
            else:
                print(f"  Failed to import '{cocktail_name}' (Status: {import_response.status_code})")
                print(f"  API Response: {import_response.text}")
                skipped_count += 1
        except requests.exceptions.ConnectionError:
            print(f"  Error: Could not connect to CocktailPi at {BASE_URL} while importing '{cocktail_name}'.")
            skipped_count += 1
        except Exception as e:
            print(f"  An unexpected error occurred during import of '{cocktail_name}': {e}")
            skipped_count += 1
        
        time.sleep(0.5) # Small delay to avoid overwhelming the API

    print(f"\n--- Import Summary ---")
    print(f"Total recipes processed: {len(cocktails_to_import)}")
    print(f"Recipes successfully imported: {imported_count}")
    print(f"Recipes skipped (due to missing data or import error): {skipped_count}")
    print(f"Recipes skipped (due to being duplicates): {duplicate_count}")
