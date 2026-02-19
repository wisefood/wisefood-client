"""
Example: Household and Member Management with the WiseFood Client

This example demonstrates how to use the WiseFood Client to manage
households, members, and their profiles.

Usage:
    export WISEFOOD_API_URL="https://api.wisefood.com/rest"
    export WISEFOOD_USERNAME="your-username"
    export WISEFOOD_PASSWORD="your-password"
    python examples/household_management.py
"""

import os
from wisefood import Client, Credentials


def main():
    # -------------------------------------------------------------------------
    # 1. Initialize the Client
    # -------------------------------------------------------------------------

    api_url = os.environ.get("WISEFOOD_API_URL", "https://wisefood.gr/rest")
    username = "liza@wisefood.gr"
    password = "A123456!"

    creds = Credentials(username=username, password=password)
    client = Client(api_url, creds)
    print("Connected to WiseFood API\n")

    # -------------------------------------------------------------------------
    # 2. Get or Create a Household
    # -------------------------------------------------------------------------

    print("=== Household Management ===\n")

    # Get the current user's household
    household = client.households.me()
    print(f"Found existing household: {household.name}")

    print(f"  ID: {household.id}")
    print(f"  Owner: {household.owner_id}")
    print(f"  Region: {household.region}")
    print(f"  Metadata: {household.metadata}")

    # Update household properties (auto-syncs to API)
    # household.name = "The Smith Family"
    # household.region = "US-CA"

    # -------------------------------------------------------------------------
    # 3. Manage Household Members
    # -------------------------------------------------------------------------

    print("\n=== Member Management ===\n")

    # Get all members of the household
    members = household.members
    print(f"Current members ({len(members)}):")
    for m in members:
        print(f"  - {m.name} ({m.age_group})")

    # Add a new member
    # new_member = household.add_member(
    #     name="Alice",
    #     age_group="adult",  # Options: baby, child, teen, young_adult, adult, middle_aged, senior
    #     image_url="https://example.com/alice.jpg"
    # )
    # print(f"\nAdded member: {new_member.name}")

    # Or create via the members proxy
    # member = client.members.create(
    #     household_id=household.id,
    #     name="Bob",
    #     age_group="child"
    # )

    # -------------------------------------------------------------------------
    # 4. Update Member Properties
    # -------------------------------------------------------------------------

    if members:
        member = members[0]
        print(f"\n=== Working with member: {member.name} ===\n")

        # Update member properties (auto-syncs to API)
        # member.name = "Alice Smith"
        # member.age_group = "young_adult"
        # member.image_url = "https://example.com/new-avatar.jpg"

        # -------------------------------------------------------------------------
        # 5. Manage Member Profile
        # -------------------------------------------------------------------------

        print("Profile:")
        profile = member.profile  # Auto-fetches from API on first access
        print(f"  Dietary groups: {profile.dietary_groups}")
        print(f"  Allergies: {profile.allergies}")
        print(f"  Nutritional preferences: {profile.nutritional_preferences}")
        print(f"  Properties: {profile.properties}")

        # Update profile (auto-syncs to API on assignment)
        profile.dietary_groups = ["vegetarian", "gluten_free"]
        profile.allergies = ["shellfish", "sesame"]
        profile.nutritional_preferences = {
            "calories": 2000,
            "protein": 50,
            "fat": 25,
            "carbs": 60,
            "food_likes": ["beef", "lamb", "milk", "cheese", "yogurt", "quinoa"],
            "food_dislikes": ["spinach", "garlic", "almond-milk", "oats"]
        }
        profile.properties = {
            "age_group": "adult",
            "feedback_history": "the user likes pizza",
            "liked_recipes": [1, 2, 3, 4, 5]
        }
        print("\nUpdated Profile:")
        print(f"  Dietary groups: {profile.dietary_groups}")
        print(f"  Allergies: {profile.allergies}")
        print(f"  Nutritional preferences: {profile.nutritional_preferences}")
        print(f"  Properties: {profile.properties}")
        

        # Available dietary groups:
        # - omnivore, vegetarian, lacto_vegetarian, ovo_vegetarian, lacto_ovo_vegetarian
        # - pescatarian, vegan, raw_vegan, plant_based, flexitarian
        # - halal, kosher, jain, buddhist_vegetarian
        # - gluten_free, nut_free, peanut_free, dairy_free, egg_free
        # - soy_free, shellfish_free, fish_free, sesame_free
        # - low_carb, low_fat, low_sodium, sugar_free, no_added_sugar
        # - high_protein, high_fiber, low_cholesterol, low_calorie
        # - keto, paleo, whole30, mediterranean, diabetic_friendly

    # -------------------------------------------------------------------------
    # 6. Additional Operations
    # -------------------------------------------------------------------------

    print("\n=== Other Operations ===\n")

    # Get a specific household by ID
    # household = client.households.get("household-id-here")

    # Get a specific member by ID
    # member = client.members.get("member-id-here")

    # List members of a household (with pagination)
    # members = client.members.list(household_id=household.id, limit=10, offset=0)

    # Refresh data from API
    # household.refresh()
    # member.refresh()
    # profile.refresh()

    # Delete operations
    # profile.delete()      # Delete member's profile
    # member.delete()       # Delete a member
    # household.delete()    # Delete the household

    # List all households (admin only)
    # all_households = client.households.list(limit=100, offset=0)

    print("Example completed successfully!")


if __name__ == "__main__":
    main()
